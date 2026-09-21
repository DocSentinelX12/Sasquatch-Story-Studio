import pytest
from scripts import verify_nccl_runtime

def test_nccl_verifier_refuses_missing_hardware(monkeypatch,tmp_path):
    monkeypatch.setattr(verify_nccl_runtime.shutil,"which",lambda _:None)
    with pytest.raises(RuntimeError,match="physical NCCL"):
        verify_nccl_runtime.verify(tmp_path/"evidence.json",worker_id="worker-a",now=100)

def test_nccl_verifier_requires_multiple_gpus(monkeypatch,tmp_path):
    monkeypatch.setattr(verify_nccl_runtime.shutil,"which",lambda _: "/bin/tool")
    class Result:
        returncode=0; stdout="GPU-aaa\n"; stderr=""
    monkeypatch.setattr(verify_nccl_runtime.subprocess,"run",lambda *a,**k:Result())
    with pytest.raises(RuntimeError,match="at least two"):
        verify_nccl_runtime.verify(tmp_path/"evidence.json",now=100)
