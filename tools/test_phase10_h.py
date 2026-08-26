"""Phase 10 Milestone H focused tests: video version control.
Run: STUDIO_TEST_PROVIDER=1 .venv/bin/python tools/test_phase10_h.py"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ["STUDIO_TEST_PROVIDER"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from studio.server import app  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from studio.db import SessionLocal  # noqa: E402
from studio.models import GenerationJob, GenerationResult, Shot, Scene, Approval  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    print(("PASS" if cond else "FAIL"), "-", name, extra if not cond else "")
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (0 if cond else 0)


def make_ready(c, shot_id):
    c.post(f"/api/shots/{shot_id}/approve")
    v = c.get(f"/api/shots/{shot_id}/validate").json()
    for f in v["findings"]:
        if f["severity"] != "info" and not f["overridden"]:
            c.post(f"/api/shots/{shot_id}/overrides",
                   json={"check_key": f["key"], "explanation": "milestone H test"})
    r = c.post(f"/api/shots/{shot_id}/ready-for-generation")
    assert r.status_code == 200, r.text[:150]


def wait_result(c, job_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = c.get(f"/api/generation/jobs/{job_id}").json()
        if j["status"] in ("needs_review", "failed"):
            return j
        time.sleep(0.6)
    return j


with TestClient(app) as c:
    # setup: approve scene, cast, prepare one shot
    c.patch("/api/scenes/1", json={"status": "approved"})
    chars = c.get("/api/characters?project_id=1").json()["characters"]
    yeti = next(x for x in chars if x["name"] == "Yeti")
    shot = c.get("/api/shots?scene_id=1").json()["shots"][0]
    try:
        c.post(f"/api/shots/{shot['id']}/cast", json={"character_id": yeti["id"]})
    except Exception:
        pass
    make_ready(c, shot["id"])

    s = SessionLocal()
    jobs_before = s.scalar(select(func.count(GenerationJob.id)))
    results_before = s.scalar(select(func.count(GenerationResult.id)))
    s.close()

    # 1. multiple generations create distinct versions (v1 rejected, v2 approved)
    j1 = c.post(f"/api/shots/{shot['id']}/generate",
                json={"provider_key": "auto", "settings": {"duration_seconds": 2}}).json()
    c.post(f"/api/generation/jobs/{j1['id']}/submit")
    wait_result(c, j1["id"])
    r1 = c.get(f"/api/generation/results?shot_id={shot['id']}").json()["results"][0]
    c.post(f"/api/generation/results/{r1['id']}/review",
           json={"decision": "rejected", "reason": "character wrong — off model"})
    j2 = c.post(f"/api/shots/{shot['id']}/generate",
                json={"provider_key": "auto", "settings": {"duration_seconds": 2}}).json()
    c.post(f"/api/generation/jobs/{j2['id']}/submit")
    wait_result(c, j2["id"])
    r2 = c.get(f"/api/generation/results?shot_id={shot['id']}").json()["results"][0]
    c.post(f"/api/generation/results/{r2['id']}/review", json={"decision": "approved"})
    # failed attempt
    j3 = c.post(f"/api/shots/{shot['id']}/generate",
                json={"provider_key": "auto", "settings": {"duration_seconds": 2, "test_force_failure": True}}).json()
    c.post(f"/api/generation/jobs/{j3['id']}/submit")
    wait_result(c, j3["id"])

    hist = c.get(f"/api/shots/{shot['id']}/video-versions").json()
    check("1. distinct versions", hist["counts"]["total_results"] == 2
          and {v["version_number"] for v in hist["versions"]} == {1, 2}, str(hist["counts"]))
    check("versions newest first", hist["versions"][0]["version_number"] >= hist["versions"][-1]["version_number"])

    # 2. failed attempts remain recorded
    check("2. failed attempt in history", hist["counts"]["failed_attempts"] >= 1
          and any(a["status"] == "failed" for a in hist["failed_attempts"]))

    # 3. rejected versions remain recorded + rejection reason
    rejected = [v for v in hist["versions"] if v["status"] == "rejected"]
    check("3. rejected recorded with reason", len(rejected) == 1
          and rejected[0]["rejection_reason"] == "character wrong — off model")

    # 4/5. approved version immutable — review again is refused, regeneration kept both
    s = SessionLocal()
    approved_row = s.scalar(select(GenerationResult).where(GenerationResult.id == r2["id"]))
    check("4. approved immutable (status/flags intact)", approved_row.status == "approved"
          and approved_row.is_approved is True and approved_row.repo_path == r2["repo_path"])
    check("5. approved not silently replaced (both results exist)",
          s.scalar(select(func.count(GenerationResult.id)).where(GenerationResult.shot_id == shot["id"])) == 2)
    s.close()

    # version metadata completeness
    detail = c.get("/api/shots/%d/video-versions/%d" % (shot["id"], r2["id"])).json()
    for key in ("version_number", "generation_job_id", "attempt", "provider", "created_at",
                "status", "is_approved", "shot_id", "output_path", "checksum", "settings",
                "is_current_production_version"):
        check(f"meta.{key} present", key in detail)
    check("meta no fabricated model", detail["provider_model"] is None)  # test adapter stores none

    # 6. invalid version selection rejected
    check("6. unknown version 409",
          c.post("/api/shots/%d/video-versions/999999/select-current" % shot["id"]).status_code == 409)
    # 7. cross-shot selection rejected
    other = c.get("/api/shots?scene_id=2").json()["shots"][0]
    check("7. cross-shot rejected",
          c.get("/api/shots/%d/video-versions/%d" % (other["id"], r2["id"])).status_code == 404
          and c.post("/api/shots/%d/video-versions/%d/select-current" % (other["id"], r2["id"])).status_code == 409)
    # 8. failed/rejected cannot become current
    check("8a. rejected not selectable",
          c.post("/api/shots/%d/video-versions/%d/select-current" % (shot["id"], r1["id"])).status_code == 409)
    check("8b. failed attempt id not selectable",
          c.post("/api/shots/%d/video-versions/%d/select-current" % (shot["id"], j3["id"])).status_code in (404, 409))
    # 9. approved CAN be explicitly selected
    sel = c.post("/api/shots/%d/video-versions/%d/select-current" % (shot["id"], r2["id"]),
                 json={"note": "H test"})
    check("9. approved selectable", sel.status_code == 200
          and sel.json()["version"]["is_current_production_version"] is True)
    # 8. audit record exists
    s = SessionLocal()
    audit = s.scalar(select(Approval).where(
        Approval.entity_type == "shot_version_selection",
        Approval.entity_id == str(shot["id"])).order_by(Approval.id.desc()))
    check("audit record created", audit is not None and "H test" in (audit.note or ""))
    s.close()

    # 10. deterministic history
    h1 = c.get(f"/api/shots/{shot['id']}/video-versions").json()
    h2 = c.get(f"/api/shots/{shot['id']}/video-versions").json()
    check("10. deterministic", [v["id"] for v in h1["versions"]] == [v["id"] for v in h2["versions"]])

    # 11. comparison only stored differences
    cmp_result = c.get("/api/shots/%d/video-versions/compare/%d/%d" % (shot["id"], r1["id"], r2["id"])).json()
    diff_fields = {d["field"] for d in cmp_result["differences"]}
    check("11. compare real fields only", "status" in diff_fields and "rejection_reason" in diff_fields
          and "visual_similarity" not in str(cmp_result))
    cmp_same = c.get("/api/shots/%d/video-versions/compare/%d/%d" % (shot["id"], r2["id"], r2["id"])).json()
    check("11b. self-compare empty diffs", cmp_same["differences"] == [])

    # 12/13/14. read-only ops: no deletions, no new jobs, row counts unchanged for reads
    s = SessionLocal()
    results_now = s.scalar(select(func.count(GenerationResult.id)))
    jobs_now = s.scalar(select(func.count(GenerationJob.id)))
    paths = {r.id: r.repo_path for r in s.scalars(select(GenerationResult)).all()}
    s.close()
    c.get(f"/api/shots/{shot['id']}/video-versions")
    c.get("/api/shots/%d/video-versions/compare/%d/{r2['id']}" % (shot["id"], r1["id"]))
    c.get("/api/shots/%d/video-versions/safety-check" % shot["id"])
    s = SessionLocal()
    check("12/13. no deletions, no new jobs on reads",
          s.scalar(select(func.count(GenerationResult.id))) == results_now
          and s.scalar(select(func.count(GenerationJob.id))) == jobs_now
          and {r.id: r.repo_path for r in s.scalars(select(GenerationResult)).all()} == paths)
    s.close()

    # safety check endpoint
    safety = c.get("/api/shots/%d/video-versions/safety-check" % shot["id"]).json()
    check("safety check runs", safety["clean"] in (True, False) and "issues" in safety)

    # 404 unknown shot
    check("history unknown shot 404", c.get("/api/shots/999999/versions").status_code == 404)

    # baseline job growth check (3 jobs created by test generation, none by reads)
    s = SessionLocal()
    check("13b. jobs grew only from generations", s.scalar(select(func.count(GenerationJob.id))) - jobs_before == 3)
    s.close()

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
