import pytest

from studio.ace_step import AceStepServiceAdapter


def test_ace_step_adapter_exposes_catalog_identity_without_false_verification():
    adapter = AceStepServiceAdapter("http://127.0.0.1:8001")
    assert adapter.info.id == "ace-step-1.5"
    assert adapter.info.verified is False
    assert "music" in adapter.info.capabilities


def test_ace_step_adapter_requires_explicit_service_url():
    with pytest.raises(ValueError):
        AceStepServiceAdapter("not-a-url")._url("health")


def test_ace_step_adapter_refuses_non_music_stage(tmp_path):
    from studio.production import ProductionRequest

    adapter = AceStepServiceAdapter("http://127.0.0.1:8001")
    with pytest.raises(RuntimeError):
        adapter.execute(ProductionRequest("dialogue", {"output_dir": str(tmp_path)}, "a" * 64))
