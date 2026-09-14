from pathlib import Path

import pytest

from studio.huggingface_hub import HubModelRef, HubFileEvidence, write_evidence


def test_huggingface_model_ref_requires_concrete_repo_id():
    with pytest.raises(ValueError):
        HubModelRef("not-a-repository").validate()


def test_huggingface_model_ref_rejects_unknown_repo_type():
    with pytest.raises(ValueError):
        HubModelRef("google/pegasus-xsum", repo_type="unknown").validate()


def test_huggingface_model_ref_accepts_pinned_revision_and_file():
    ref = HubModelRef(
        "google/pegasus-xsum",
        revision="0123456789abcdef0123456789abcdef01234567",
        filename="config.json",
    )
    ref.validate()


def test_huggingface_evidence_contains_immutable_file_identity(tmp_path: Path):
    evidence = HubFileEvidence(
        repo_id="google/pegasus-xsum",
        repo_type="model",
        requested_revision=None,
        resolved_revision="0123456789abcdef0123456789abcdef01234567",
        filename="config.json",
        local_path=str(tmp_path / "config.json"),
        bytes=123,
        sha256="a" * 64,
        license=None,
        private=False,
        gated=False,
    )
    target = tmp_path / "evidence.json"
    write_evidence(target, evidence)
    text = target.read_text()
    assert '"resolved_revision": "0123456789abcdef0123456789abcdef01234567"' in text
    assert '"sha256": "' + "a" * 64 + '"' in text


def test_install_script_uses_official_free_huggingface_client_and_real_download():
    script = Path("scripts/install_huggingface.py").read_text()
    assert 'pip", "install", "huggingface_hub>=1.0,<2' in script
    assert 'from huggingface_hub import HfApi, hf_hub_download' in script
    assert 'api.model_info(VERIFY_REPO, files_metadata=True, token=token)' in script
    assert 'hf_hub_download(' in script
    assert 'paid_service_used": False' in script
    assert 'runtime_generation_verified": False' in script


def test_engine_workflow_has_dedicated_huggingface_verification():
    workflow = Path(".github/workflows/install-all-engines.yml").read_text()
    assert "Install Hugging Face Hub" in workflow
    assert "scripts/install_huggingface.py" in workflow
    assert "engine-installations/huggingface/installation-evidence.json" in workflow
