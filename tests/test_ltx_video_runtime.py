from pathlib import Path

import pytest

from studio.engine_adapters import build_ltx_video_runtime_config
from studio.ltx_video_runtime import (
    CHECKPOINT_FILENAME,
    CHECKPOINT_SHA256,
    MODEL_REVISION,
    SOURCE_REVISION,
    UPSCALER_FILENAME,
    UPSCALER_SHA256,
    build_ltx_video_command,
    validate_num_frames,
)


def test_ltx_provenance_is_pinned():
    assert SOURCE_REVISION == "4b2d053057623ddd4d0a1d3e9cd28890e9ef487f"
    assert MODEL_REVISION == "19560f8b59a58a0431baf39c78cd8a60a86b9c33"
    assert CHECKPOINT_FILENAME == "ltxv-2b-0.9.8-distilled.safetensors"
    assert UPSCALER_FILENAME == "ltxv-spatial-upscaler-0.9.8.safetensors"
    assert len(CHECKPOINT_SHA256) == 64
    assert len(UPSCALER_SHA256) == 64


def test_ltx_requires_official_frame_contract():
    validate_num_frames(121)
    validate_num_frames(9)
    with pytest.raises(ValueError, match=r"8N\+1"):
        validate_num_frames(120)


def test_ltx_command_binds_prompt_image_and_output(tmp_path: Path):
    command = build_ltx_video_command(
        python_executable="python",
        repository=(tmp_path / "LTX-Video").resolve(),
        model_path=(tmp_path / "models").resolve(),
        prompt="make the Sasquatch bounce",
        image_path="{image_path}",
        output_token="{output}",
    )
    assert command[0:2] == ("python", "scripts/run_ltx_video.py")
    assert "make the Sasquatch bounce" in command
    assert "{image_path}" in command
    assert "{output}" in command
    assert "--model-path" in command


def test_ltx_production_runtime_config_is_connected(tmp_path: Path):
    config = build_ltx_video_runtime_config(
        repository=tmp_path / "LTX-Video",
        model_path=tmp_path / "models",
        output_path=str(tmp_path / "renders" / "shot.mp4"),
    )
    assert config.engine_id == "ltx-video"
    assert config.command[1] == "scripts/run_ltx_video.py"
    assert "{prompt}" in config.command
    assert "{image_path}" in config.command
    assert "{output}" in config.command
    assert config.working_directory == str((tmp_path / "LTX-Video").resolve())
