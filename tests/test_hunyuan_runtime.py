from pathlib import Path
import sys

import pytest

from scripts.verify_hunyuanvideo15_runtime import build_execution_command, require_cuda


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


def test_hunyuan_runtime_guard_rejects_non_cuda_runtime(monkeypatch):
    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return False

    class FakeTorch:
        cuda = FakeCuda()

    monkeypatch.setitem(sys.modules, "torch", FakeTorch())
    with pytest.raises(RuntimeError, match="CUDA GPU"):
        require_cuda()
