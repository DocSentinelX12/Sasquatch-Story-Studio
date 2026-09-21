import pytest
from scripts import verify_gpu_runtime

def test_gpu_runtime_verifier_refuses_cpu_only_host(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_gpu_runtime.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="physical NVIDIA"):
        verify_gpu_runtime.verify(tmp_path / "evidence.json", now=100)

def test_gpu_runtime_evidence_records_real_gpu_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_gpu_runtime.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    class Result:
        returncode=0
        stdout="GPU-aaa\n"
        stderr=""
    monkeypatch.setattr(verify_gpu_runtime, "_run", lambda command, timeout=60: Result())
    evidence=verify_gpu_runtime.verify(tmp_path/"evidence.json", now=100)
    assert evidence["gpu_uuids"]==["GPU-aaa"]; assert evidence["recorded_at"]==100
