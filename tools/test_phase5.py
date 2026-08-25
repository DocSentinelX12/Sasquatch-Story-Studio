"""Phase 5 verification suite — mocked providers only, no paid API calls.

Run:  .venv/bin/python tools/test_phase5.py

Covers: provider registry + adapter contracts (researched endpoints),
capability gating, automatic-mode intersection, security, the full shot
generation workflow, queue lifecycle, retry, versioning, review, and
Phase 1–4 regression. Real adapters are exercised through httpx.MockTransport.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ["STUDIO_TEST_PROVIDER"] = "1"   # clearly-marked test adapter, no network

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from studio.server import app  # noqa: E402
from studio.providers.adapters import get_video_adapter  # noqa: E402
from studio.providers.adapters.seedance import SeedanceAdapter  # noqa: E402
from studio.providers.adapters.veo import VeoAdapter  # noqa: E402
from studio.providers.adapters.wan import WanAdapter  # noqa: E402
from studio.providers.capabilities import ProviderCapabilities  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    print(("PASS" if cond else "FAIL"), "-", name, extra if not cond else "")
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (0 if cond else 1)


PKG = {
    "visual_style": "2D cartoon", "camera": {"shot_type": "medium", "movement": "push_in"},
    "characters": [{"name": "Yeti", "standard_appearance": "dark fur", "never_changes": ["barefoot"]}],
    "location": {"name": "Big Cedar Home"},
    "action": {"description": "Yeti reacts"},
    "continuity_requirements": {"barefoot_rule": "ALL CHARACTERS ARE ALWAYS BAREFOOT."},
    "negative_constraints": ["redesign"],
    "dialogue_timing": {"shot_dialogue": ["YETI: Echo!"]},
    "frame_references": {},
}


def mock(handler):
    return httpx.MockTransport(handler)


# =====================================================================
# A + B: adapter contracts (researched endpoints, mocked responses)
# =====================================================================
def test_adapter_contracts():
    veo = VeoAdapter("k", transport=mock(lambda r: httpx.Response(200, json={"name": "operations/abc"})))
    t = veo.translate(PKG, {"aspect_ratio": "16:9", "duration_seconds": 8})
    check("veo endpoint contract", t["url"] == "models/veo-3.1-generate-preview:predictLongRunning", t["url"])
    check("veo base url contract", veo.base_url == "https://generativelanguage.googleapis.com/v1beta")
    check("veo prompt carries barefoot rule + dialogue", "BAREFOOT" in t["body"]["instances"][0]["prompt"]
          and "Echo!" in t["body"]["instances"][0]["prompt"])
    handle = veo.submit(t)
    check("veo submit -> operation name", handle.provider_job_id == "operations/abc")

    poll_states = iter([httpx.Response(200, json={"done": False}),
                        httpx.Response(200, json={"done": True, "response": {
                            "generateVideoResponse": {"generatedSamples": [
                                {"video": {"uri": "https://files/x.mp4", "mimeType": "video/mp4"}}]}}})])
    veo2 = VeoAdapter("k", transport=mock(lambda r: next(poll_states)))
    check("veo poll generating", veo2.poll("operations/abc").state == "generating")
    result = veo2.fetch_result("operations/abc")
    check("veo result uri", result.download_url == "https://files/x.mp4")

    seed = SeedanceAdapter("k", transport=mock(lambda r: httpx.Response(200, json={"id": "task-9"})))
    t2 = seed.translate(PKG, {"duration_seconds": 5, "resolution": "720p", "aspect_ratio": "16:9", "seed": 7})
    check("seedance endpoint + body contract",
          "contents/generations/tasks" in seed.translate(PKG, {} if False else {"duration_seconds": 5})["url"]
          and seed.base_url == "https://ark.cn-beijing.volces.com/api/v3"
          and t2["body"]["duration"] == 5 and t2["body"]["seed"] == 7)
    check("seedance submit -> id", seed.submit(t2).provider_job_id == "task-9")
    seed2 = SeedanceAdapter("k", transport=mock(lambda r: httpx.Response(200, json={
        "status": "succeeded", "content": {"video_url": "https://ark/v.mp4"}})))
    check("seedance poll + fetch", seed2.poll("task-9").state == "succeeded"
          and seed2.fetch_result("task-9").download_url == "https://ark/v.mp4")

    wan = WanAdapter("k", transport=mock(lambda r: httpx.Response(200, json={"output": {"task_id": "w-1"}})))
    t3 = wan.translate(PKG, {"resolution": "720P"})
    check("wan endpoint + model contract",
          t3["url"] == "services/aigc/video-generation/video-synthesis"
          and t3["body"]["model"] == "wan2.2-t2v-plus"
          and wan.base_url == "https://dashscope-intl.aliyuncs.com/api/v1")
    check("wan submit -> task_id", wan.submit(t3).provider_job_id == "w-1")
    wan2 = WanAdapter("k", transport=mock(lambda r: httpx.Response(200, json={
        "output": {"task_status": "SUCCEEDED", "video_url": "https://wan/v.mp4"}})))
    check("wan poll + fetch", wan2.poll("w-1").state == "succeeded"
          and wan2.fetch_result("w-1").download_url == "https://wan/v.mp4")

    # auth / api error mapping
    auth = VeoAdapter("bad", transport=mock(lambda r: httpx.Response(401, json={"error": {}})))
    check("veo auth error mapped", auth.validate_connection() == "auth_error")
    seed_auth = SeedanceAdapter("bad", transport=mock(lambda r: httpx.Response(403, json={})))
    check("seedance auth error mapped", seed_auth.validate_connection() == "auth_error")
    seed_ok = SeedanceAdapter("k", transport=mock(lambda r: httpx.Response(404, json={})))
    check("seedance sentinel-404 proves credentials", seed_ok.validate_connection() == "connected")
    api_err = VeoAdapter("k", transport=mock(lambda r: httpx.Response(500, json={})))
    check("api error mapped", api_err.validate_connection() == "api_error")


# =====================================================================
# C: capability gating
# =====================================================================
def test_capabilities():
    veo_caps = VeoAdapter("test").capabilities()
    check("veo duration gate", bool(veo_caps.validate_settings({"duration_seconds": 99})))
    check("veo no seed", bool(veo_caps.validate_settings({"seed": 1})))
    check("veo aspect gate", bool(veo_caps.validate_settings({"aspect_ratio": "1:1"})))
    check("veo last-frame unsupported", not veo_caps.last_frame and not veo_caps.start_end_frames)
    seed_caps = SeedanceAdapter("test").capabilities()
    check("seedance seed supported", not seed_caps.validate_settings({"seed": 3}))
    check("seedance resolution gate", bool(seed_caps.validate_settings({"resolution": "4k"})))
    from studio.services.generation_service import validate_for_provider, prioritize_references
    pkg_frames = {"frame_references": {
        "first_frame": [{"path": "renders/a.png"}],
        "last_frame": [{"path": "renders/b.png"}]}}
    report = validate_for_provider({"frame_references": {}}, "seedance", {})
    check("validate_for_provider ok baseline", report["ok"])
    sub, skipped = prioritize_references(pkg_frames, seed_caps)
    check("seedance URL-only refs skipped with reasons",
          len(skipped) == 2 and all("URL" in s["reason"] for s in skipped), str(skipped))
    veo_sub, _ = prioritize_references(pkg_frames, veo_caps)
    check("veo keeps local first frame, drops last (1 slot)",
          [s["purpose"] for s in veo_sub] == ["first_frame"], str([s["purpose"] for s in veo_sub]))
    many = {"frame_references": {"storyboard_image": [{"path": f"renders/sb{i}.png"} for i in range(6)]}}
    sub2, skipped2 = prioritize_references(many, veo_caps)
    check("slot limit enforced", len(sub2) == veo_caps.max_reference_slots and skipped2
          and all("limit" in s["reason"] for s in skipped2), str([s["reason"] for s in skipped2]))


# =====================================================================
# D–I: full lifecycle through the API (TEST adapter, no network)
# =====================================================================
def wait_job(c, job_id, until=("needs_review", "failed"), timeout=15):
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        job = c.get(f"/api/generation/jobs/{job_id}").json()
        if job["status"] in until:
            return job
        time.sleep(0.4)
    return job


def test_lifecycle():
    with TestClient(app) as c:
        # fresh draft shot on scene 2 (untouched by earlier runs in same DB)
        scenes = c.get("/api/scenes", params={"episode_id": 1}).json()["scenes"]
        scene = scenes[1]
        c.patch(f"/api/scenes/{scene['id']}", json={"status": "approved"})
        shot = c.post("/api/shots", json={
            "scene_id": scene["id"], "title": "P5 final verification shot",
            "description": "Verification beat", "shot_type": "medium",
            "camera_angle": "eye_level", "camera_movement": "push_in",
            "duration_seconds": 2}).json()
        check("shot created draft", shot["status"] == "draft")
        c.post(f"/api/scenes/{scene['id']}/cast", json={"character_id": 1})

        v = c.get(f"/api/shots/{shot['id']}/validate").json()
        for f in v["findings"]:
            if f["severity"] != "info" and not f["overridden"]:
                c.post(f"/api/shots/{shot['id']}/overrides", json={
                    "check_key": f["key"], "explanation": "verification run — no creator artwork in sandbox"})
        c.post(f"/api/shots/{shot['id']}/approve")
        ready = c.post(f"/api/shots/{shot['id']}/ready-for-generation")
        check("shot ready for generation", ready.status_code == 200 and ready.json()["shot"]["status"] == "ready_for_generation")

        # preview before submitting (PART 18)
        preview = c.get(f"/api/shots/{shot['id']}/preview-request",
                        params={"provider_key": "auto", "settings": '{"duration_seconds": 2}'}).json()
        check("auto resolves test provider + exact request", preview["provider"] == "test-echo"
              and preview["translated"]["body"]["test_marker"].startswith("TEST ADAPTER"))

        # async submission does not block
        job = c.post(f"/api/shots/{shot['id']}/generate",
                     json={"provider_key": "auto", "settings": {"duration_seconds": 2}}).json()
        check("draft job with translated request + package version",
              job["status"] == "draft" and job["translated_request"] and job["package_version"] == 1)
        start = time.time()
        submitted = c.post(f"/api/generation/jobs/{job['id']}/submit").json()
        check("submit returns fast (async)", time.time() - start < 5
              and submitted["provider_job_id"].startswith("test-"))
        final = wait_job(c, job["id"])
        check("completed -> needs_review with usage", final["status"] == "needs_review"
              and final["usage"] and final["provider_job_id"])
        check("shot moved to generating", c.get(f"/api/shots/{shot['id']}").json()["status"] == "generating")

        results = c.get("/api/generation/results", params={"shot_id": shot["id"]}).json()["results"]
        check("versioned result v1 stored (test-labelled)", len(results) == 1
              and results[0]["version_number"] == 1 and results[0]["test_adapter"] is True)
        check("result file serves", c.get(f"/api/generation/results/{results[0]['id']}/file").status_code == 200)

        # review: reject requires reason
        r = c.post(f"/api/generation/results/{results[0]['id']}/review", json={"decision": "rejected"})
        check("reject needs reason", r.status_code == 422)
        c.post(f"/api/generation/results/{results[0]['id']}/review",
               json={"decision": "rejected", "reason": "verification reject"})
        check("rejected -> shot needs_revision", c.get(f"/api/shots/{shot['id']}").json()["status"] == "needs_revision")

        # second version from needs_revision, then approve
        job2 = c.post(f"/api/shots/{shot['id']}/generate",
                      json={"provider_key": "auto", "settings": {"duration_seconds": 2}}).json()
        c.post(f"/api/generation/jobs/{job2['id']}/submit")
        wait_job(c, job2["id"])
        results = c.get("/api/generation/results", params={"shot_id": shot["id"]}).json()["results"]
        versions = sorted(r["version_number"] for r in results)
        check("v1 preserved + v2 stored", versions == [1, 2], str(versions))
        v2 = [r for r in results if r["version_number"] == 2][0]
        c.post(f"/api/generation/results/{v2['id']}/review", json={"decision": "approved"})
        check("approved -> shot complete + generated", c.get(f"/api/shots/{shot['id']}").json()["status"] == "complete")

        # another version on a COMPLETE shot (approved version untouched)
        job3 = c.post(f"/api/shots/{shot['id']}/generate",
                      json={"provider_key": "auto", "settings": {"duration_seconds": 2}}).json()
        check("complete shot can generate another version", job3["attempt"] == 3)
        c.post(f"/api/generation/jobs/{job3['id']}/cancel")
        check("cancel works", c.get(f"/api/generation/jobs/{job3['id']}").json()["status"] == "cancelled")
        check("approved result still intact", c.get(f"/api/generation/results/{v2['id']}/file").status_code == 200)

        # retry on failure with provider/settings changes
        jobf = c.post(f"/api/shots/{shot['id']}/generate",
                      json={"provider_key": "auto", "settings": {"test_force_failure": True}}).json()
        c.post(f"/api/generation/jobs/{jobf['id']}/submit")
        failed = wait_job(c, jobf["id"], until=("failed",))
        check("failure recorded with code + provider job id",
              failed["status"] == "failed" and failed["error_code"] == "generation_failed"
              and failed["provider_job_id"])
        retry = c.post(f"/api/generation/jobs/{jobf['id']}/retry",
                       json={"settings_overrides": {"test_force_failure": False}}).json()
        check("retry = new attempt, failed kept", retry["attempt"] == jobf["attempt"] + 1
              and c.get(f"/api/generation/jobs/{jobf['id']}").json()["status"] == "failed")

        # queue summary states
        counts = c.get("/api/generation/jobs").json()["counts_by_status"]
        check("queue states present", {"failed", "cancelled", "approved", "rejected"} <= set(counts), str(counts))


# =====================================================================
# D2: registry honesty (run WITHOUT the test env in a subprocess-like way)
# =====================================================================
def test_registry_honesty():
    from studio.providers.registry import provider_status_list
    providers = provider_status_list()
    real = [p for p in providers if p["key"] in ("veo", "seedance", "wan")]
    check("3 real providers registered with caps", len(real) == 3 and all(p["caps"] for p in real))
    check("real providers honest (not connected, env named only)",
          all(p["status"] in ("not_configured", "available") and not p["connected"] for p in real))
    check("no credential values in provider payload", "Bearer " not in str(providers))
    test = [p for p in providers if p["is_test"]]
    check("test adapter present (enabled in this run) + marked", test and test[0]["is_test"])


# =====================================================================
# K: phases 1–4 regression
# =====================================================================
def test_phase_regression():
    with TestClient(app) as c:
        endpoints = [
            "/api/dashboard", "/api/projects", "/api/characters", "/api/assets",
            "/api/episodes", "/api/episodes/1", "/api/episodes/1/board",
            "/api/story-bible?project_id=1", "/api/canon?project_id=1", "/api/stories",
            "/api/scenes", "/api/scenes/1/director", "/api/shots",
            "/api/shots/1/generation-package", "/api/world/locations", "/api/world/props",
            "/api/generation/jobs", "/api/providers", "/api/system/health",
            "/api/assets/tags", "/api/search?q=yeti",
        ]
        bad = [u for u in endpoints if c.get(u).status_code != 200]
        check("phase 1-5 endpoints all 200", not bad, str(bad))
        check("canon validator endpoint passes", c.post("/api/system/validate-content").json()["passed"])


def main():
    test_adapter_contracts()
    test_capabilities()
    test_registry_honesty()
    test_lifecycle()
    test_phase_regression()
    print(f"\nRESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
