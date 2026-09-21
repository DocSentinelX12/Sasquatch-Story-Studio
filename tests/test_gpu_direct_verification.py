import pytest
from scripts import verify_gpu_direct

def test_gpu_direct_verifier_requires_explicit_command(monkeypatch,tmp_path):
    monkeypatch.setattr(verify_gpu_direct.shutil,"which",lambda _: "/bin/nvidia-smi")
    with pytest.raises(ValueError,match="explicit GPU-direct"):
        verify_gpu_direct.verify(tmp_path/"evidence.json","",worker_pair=("a","b"),gpu_pair=("GPU-a","GPU-b"),interface="ib0",now=100)

def test_gpu_direct_verifier_requires_explicit_network_identity(monkeypatch,tmp_path):
    monkeypatch.setattr(verify_gpu_direct.shutil,"which",lambda _: "/bin/nvidia-smi")
    with pytest.raises(ValueError,match="worker pair"):
        verify_gpu_direct.verify(tmp_path/"evidence.json","echo ok",now=100)
