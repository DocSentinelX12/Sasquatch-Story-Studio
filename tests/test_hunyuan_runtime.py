from pathlib import Path
import sys

import pytest

from scripts.verify_hunyuanvideo15_runtime import require_cuda
from studio.hunyuan_runtime import build_hunyuan_command


def test_hunyuan_execution_command_matches_official_source_contract(tmp_path: Path):
    repository = tmp_path / "HunyuanVideo-1.5"
    model_path = tmp_path / "ckpts"
    command = build_hunyuan_command(
        torchrun_executable="torchrun",
        repository=repository,
        prompt="verification prompt",
        model_path=model_path,
        image_path=None,
        output_token="{output}",
        seed=7,
    )

    assert command[:3] == ("torchrun", "--nproc_per_node=1", "generate.py")
    assert "{output}" in command
    assert command[command.index("--model_path") + 1] == str(model_path.resolve())
    assert command[command.index("--image_path") + 1] == "none"
    assert command[command.index("--video_length") + 1] == "9"
    assert command[command.index("--num_inference_steps") + 1] == "50"
    assert "--enable_step_distill" not in command


def test_hunyuan_execution_command_supports_creator_reference_image(tmp_path: Path):
    reference = tmp_path / "meta-reference.webp"
    command = build_hunyuan_command(
        torchrun_executable="torchrun",
        repository=tmp_path / "HunyuanVideo-1.5",
        model_path=tmp_path / "ckpts",
        prompt="animate the character naturally",
        image_path=reference,
        output_token="{output}",
        seed=1,
    )
    assert command[command.index("--image_path") + 1] == str(reference.resolve())


def test_hunyuan_command_never_uses_a_remote_paid_api(tmp_path: Path):
    command = build_hunyuan_command(
        torchrun_executable="torchrun",
        repository=tmp_path / "HunyuanVideo-1.5",
        model_path=tmp_path / "ckpts",
        prompt="verification prompt",
        image_path=None,
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
