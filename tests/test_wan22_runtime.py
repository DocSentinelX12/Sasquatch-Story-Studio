from pathlib import Path

import pytest

from studio.engine_adapters import build_wan22_runtime_config
from studio.engine_registry import catalog_engines_for, get_catalog_engine
from studio.wan22_runtime import (
    ENGINE_ID,
    MODEL_REPOSITORY,
    OFFICIAL_REPOSITORY,
    OFFICIAL_SOURCE_REVISION,
    build_wan22_command,
)


def test_catalog_entry_is_explicit_and_not_runtime_verified():
    engine = get_catalog_engine(ENGINE_ID)
    assert engine.version_family == "2.2"
    assert engine.capabilities == ("video_generation", "image_generation")
    assert engine.license == "Apache-2.0"
    assert engine.runtime_verified is False
    assert engine.checkpoint_verified is False
    assert engine.source_revision == OFFICIAL_SOURCE_REVISION
    assert engine in catalog_engines_for("video_generation")


def test_official_t2v_command_uses_real_studio_tokens(tmp_path: Path):
    command = build_wan22_command(
        python_executable="python",
        repository=tmp_path / "Wan2.2",
        model_path=tmp_path / "Wan2.2-T2V-A14B",
        prompt="{prompt}",
        output_token="{output}",
    )
    assert command[:2] == ("python", "generate.py")
    assert "--task" in command and "t2v-A14B" in command
    assert "--ckpt_dir" in command
    assert "--prompt" in command and "{prompt}" in command
    assert "--save_file" in command and "{output}" in command
    assert "--offload_model" in command and "True" in command


def test_frame_contract_is_enforced(tmp_path: Path):
    with pytest.raises(ValueError, match=r"4N\+1"):
        build_wan22_command(
            python_executable="python",
            repository=tmp_path / "Wan2.2",
            model_path=tmp_path / "model",
            prompt="test",
            output_token="{output}",
            frame_num=80,
        )


def test_runtime_config_connects_prompt_and_output(tmp_path: Path):
    config = build_wan22_runtime_config(
        repository=tmp_path / "Wan2.2",
        model_path=tmp_path / "Wan2.2-T2V-A14B",
        output_path=str(tmp_path / "renders" / "shot.mp4"),
    )
    assert config.engine_id == ENGINE_ID
    assert "{prompt}" in config.command
    assert "{output}" in config.command
    assert config.working_directory == str((tmp_path / "Wan2.2").resolve())
    assert config.timeout_seconds == 21600


def test_provenance_is_pinned():
    assert OFFICIAL_REPOSITORY == "https://github.com/Wan-Video/Wan2.2"
    assert MODEL_REPOSITORY == "Wan-AI/Wan2.2-T2V-A14B-Diffusers"
    assert OFFICIAL_SOURCE_REVISION == "42bf4cfaa384bc21833865abc2f9e6c0e67233dc"
