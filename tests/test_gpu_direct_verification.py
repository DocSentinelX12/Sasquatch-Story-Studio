import pytest
from scripts import verify_gpu_direct

def test_gpu_direct_verifier_requires_explicit_command(monkeypatch,tmp_path):
    monkeypatch.setattr(verify_gpu_direct.shutil,"which",lambda _: "/bin/nvidia-smi")
    with pytest.raises(ValueError,match="explicit GPU-direct"):
        verify_gpu_direct.verify(tmp_path/"evidence.json","",now=100)
