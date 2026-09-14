from studio.runtime_probe import probe_engines


def test_probe_reports_every_curated_engine():
    statuses = probe_engines()
    assert statuses
    assert {s.engine_id for s in statuses} >= {"wan2.1", "ltx-video", "opentoonz", "blender", "comfyui", "piper", "rhubarb-lip-sync"}
    assert all(s.reason for s in statuses)


def test_probe_does_not_claim_production_verification():
    statuses = {s.engine_id: s for s in probe_engines()}
    assert "production verification" in statuses["wan2.1"].reason or "entrypoint" in statuses["wan2.1"].reason
