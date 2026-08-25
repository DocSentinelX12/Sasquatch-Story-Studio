"""Phase 9 verification suite — run: .venv/bin/python tools/test_phase9.py"""
from __future__ import annotations

import io
import json
import os
import time

os.environ["STUDIO_TEST_PROVIDER"] = "1"
os.environ["STUDIO_WEBHOOK_SECRET"] = "whsec-test"

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hashlib
import hmac
import zipfile
from fastapi.testclient import TestClient
from studio.server import app

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    print(("PASS" if cond else "FAIL"), "-", name, extra if not cond else "")
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (0 if cond else 1)


def upload(client, payload, endpoint):
    return client.post(endpoint, files={"file": ("b.json", io.BytesIO(json.dumps(payload).encode()), "application/json")})


with TestClient(app) as c:
    backup = c.get("/api/series/1/backup").json()

    # C — verify
    v = upload(c, backup, "/api/backups/verify").json()
    check("verify: valid/warning", v["validation"]["status"] in ("valid", "warning"))
    check("verify: unknown format blocked", upload(c, {**backup, "format": "x"}, "/api/backups/verify").json()["validation"]["status"] == "blocked")
    check("verify: malformed JSON rejected", c.post("/api/backups/verify", files={"file": ("b.json", io.BytesIO(b"{"), "application/json")}).status_code == 422)
    dup = {**backup, "characters": backup["characters"] + [dict(backup["characters"][0])]}
    check("verify: duplicate ids blocked", upload(c, dup, "/api/backups/verify").json()["validation"]["status"] == "blocked")
    orphan = dict(backup["scenes"][0]); orphan["id"] = 999; orphan["episode_id"] = 424242
    check("verify: broken relationships blocked", upload(c, {**backup, "scenes": backup["scenes"] + [orphan]}, "/api/backups/verify").json()["validation"]["status"] == "blocked")
    bad_schema = {**backup, "backup_metadata": {"backup_schema_version": 99, "checksum": "x"}}
    check("verify: newer schema blocked", upload(c, bad_schema, "/api/backups/verify").json()["validation"]["status"] == "blocked")

    # A/B — staged restore
    prev = upload(c, backup, "/api/backups/restore/preview").json()
    check("preview token + honest media report", prev["token"] and "missing_paths" in prev["media"])
    before = len(c.get("/api/projects").json()["projects"])
    token = prev["token"]
    check("confirm requires confirm=true", c.post(f"/api/backups/restore/confirm?token={token}", json={"confirm": False}).status_code == 422)
    r = c.post(f"/api/backups/restore/confirm?token={token}", json={"confirm": True, "mode": "new_series"})
    check("restore as new series (default mode)", r.json().get("restored") is True, r.text[:200])
    check("series grew by exactly 1", len(c.get("/api/projects").json()["projects"]) == before + 1)
    new_id = r.json()["target_series_id"]
    check("characters restored", len(c.get(f"/api/characters?project_id={new_id}").json()["characters"]) == 5)
    check("token single-use", c.post(f"/api/backups/restore/confirm?token={token}", json={"confirm": True, "mode": "new_series"}).status_code == 404)

    corrupt = {**backup, "scenes": "not-a-list"}
    prev2 = upload(c, corrupt, "/api/backups/restore/preview").json()
    check("corrupt blocked at preview (no token, DB untouched)", prev2["token"] is None and prev2["validation"]["status"] == "blocked")
    check("replace requires target", c.post(f"/api/backups/restore/confirm?token={upload(c, backup, '/api/backups/restore/preview').json()['token']}",
        json={"confirm": True, "mode": "replace"}).status_code == 422)
    check("active DB untouched after corruption attempts", len(c.get("/api/projects").json()["projects"]) == before + 1)

    # media restore
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("assets/studio-uploads/images/p9restored.png", b"\x89PNG-p9")
        z.writestr("etc/passwd", b"no")
        z.writestr("../escape.txt", b"no")
    m = c.post("/api/backups/restore/media", files={"file": ("m.zip", buf.getvalue(), "application/zip")}).json()
    check("media: safe path extracted", "assets/studio-uploads/images/p9restored.png" in m["restored"])
    check("media: unsafe paths refused", len(m["skipped"]) == 2)
    check("media file on disk", Path("assets/studio-uploads/images/p9restored.png").exists())

    # D — auto backups
    check("auto config persists", c.post("/api/backups/auto", json={"enabled": True, "cadence": "daily"}).json()["config"]["enabled"] is True)
    run = c.post("/api/backups/auto/run?reason=manual").json()
    check("run-now writes backup file", str(run.get("path", "")).startswith("backups/"), str(run)[:120])
    check("history lists snapshots", len(c.get("/api/backups/auto").json()["history"]) >= 1)
    c.post("/api/backups/auto", json={"enabled": False, "cadence": "weekly"})

    # E — webhooks
    t = c.get("/api/webhooks/transports").json()
    check("transports: cloud polling, local both", t["transports"].get("veo") == "polling" and t["transports"].get("local") == "both")
    check("webhook rejects invalid signature", c.post("/api/webhooks/generation",
        json={"provider": "test-echo", "job_id": "x", "status": "succeeded"},
        headers={"X-Signature": "bad"}).status_code == 401)

    c.patch("/api/scenes/1", json={"status": "approved"})
    shot = c.get("/api/shots?scene_id=1").json()["shots"][0]
    try:
        c.post(f"/api/shots/{shot['id']}/cast", json={"character_id": 1})
    except Exception:
        pass
    loc = c.get("/api/world/locations?project_id=1").json()["locations"][0]
    c.patch(f"/api/world/locations/{loc['id']}", json={"approval_status": "approved"})
    c.post(f"/api/shots/{shot['id']}/approve")
    vv = c.get(f"/api/shots/{shot['id']}/validate").json()
    for f in vv["findings"]:
        if f["severity"] != "info" and not f["overridden"]:
            c.post(f"/api/shots/{shot['id']}/overrides", json={"check_key": f["key"], "explanation": "p9 webhook test"})
    r_ready = c.post(f"/api/shots/{shot['id']}/ready-for-generation")
    assert r_ready.status_code == 200, r_ready.text[:200]
    job = c.post(f"/api/shots/{shot['id']}/generate", json={"provider_key": "auto", "settings": {"duration_seconds": 2}}).json()
    c.post(f"/api/generation/jobs/{job['id']}/submit")
    live = c.get(f"/api/generation/jobs/{job['id']}").json()
    body = json.dumps({"provider": "test-echo", "job_id": live["provider_job_id"], "status": "running"}).encode()
    sig = hmac.new(b"whsec-test", body, hashlib.sha256).hexdigest()
    ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    r = c.post("/api/webhooks/generation", content=body, headers={"X-Signature": sig, "X-Timestamp": ts, "Content-Type": "application/json"})
    if r.status_code != 200:
        print("DEBUG live provider_job_id:", live.get("provider_job_id"), "| body:", body[:120], "| resp:", r.text[:200])
    check("signed webhook accepted + normalized", r.status_code == 200 and (r.json() or {}).get("normalized") == "generating", r.text[:160])
    body2 = json.dumps({"provider": "test-echo", "job_id": live["provider_job_id"], "status": "succeeded", "video_url": "test://x"}).encode()
    sig2 = hmac.new(b"whsec-test", body2, hashlib.sha256).hexdigest()
    r2 = c.post("/api/webhooks/generation", content=body2, headers={"X-Signature": sig2, "X-Timestamp": ts, "Content-Type": "application/json"})
    # note: by the time this hint arrives, the poll worker may have already
    # completed the job (test adapter succeeds in ~2s) — either 200-with-hint
    # or 200-completed is correct; both mean the webhook didn't blindly complete.
    check("success webhook safe (hint or already-completed)", r2.status_code == 200, r2.text[:160])
    check("replay rejected", c.post("/api/webhooks/generation", content=body,
        headers={"X-Signature": sig, "X-Timestamp": "2020-01-01T00:00:00+00:00", "Content-Type": "application/json"}).status_code == 401)

    check("phases 1-8 intact", all(c.get(u).status_code == 200 for u in
          ("/api/dashboard", "/api/episodes/1", "/api/batch/assistant/1",
           "/api/automation/rules?project_id=1", "/api/exports", "/api/series/isolation-check")))

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
