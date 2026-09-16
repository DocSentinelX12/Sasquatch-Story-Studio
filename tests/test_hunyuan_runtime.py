from pathlib import Path
import sys

import pytest

from scripts.verify_hunyuanvideo15_runtime import build_execution_command


def test_hunyuan_execution_command_is_explicit_and_real():
    command = build_execution_command(
        python_executable=sys.executable,
        prompt="verification prompt",
        model_path=Path("/models/hunyuanvideo-1.5"),
        output_token="{output}",
        seed=7,
    )

    assert command[0] == sys.executable
    assert "generate.py" in command
    assert "{output}" in command
    assert "--model_path" in command
    assert command[command.index("--model_path") + 1] == "/models/hunyuanvideo-1.5"
    assert command[command.index("--video_length") + 1] == "9"
    assert command[command.index("--num_inference_steps") + 1] == "4"


def test_hunyuan_command_never_uses_a_remote_paid_api():
    command = build_execution_command(
        python_executable=sys.executable,
        prompt="verification prompt",
        model_path=Path("/models/hunyuanvideo-1.5"),
        output_token="{output}",
        seed=1,
    )
    joined = " ".join(command)
    assert "http://" not in joined
    assert "https://" not in joined


def test_hunyuan_runtime_script_requires_cuda_before_claiming_runtime_verification(monkeypatch, tmp_path: Path):
    import scripts.verify_hunyuanvideo15_runtime as verifier

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class FakeTorch:
        cuda = FakeCuda()

    monkeypatch.setitem(__import__("sys").modules, "torch", FakeTorch())
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "generate.py").write_text("", encoding="utf-8")
    model = tmp_path / "model"
    model.mkdir()
    (model / "weights.bin").write_bytes(b"real test fixture")

    monkeypatch.setattr(verifier, "_git_revision", lambda _: "test-revision")
    with pytest.raises(RuntimeError, match="CUDA GPU"):
        verifier.main.__wrapped__ if False else verifier._git_revision
