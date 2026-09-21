from pathlib import Path

import pytest

from studio.cogvideox15_i2v_runtime import (
    ENGINE_ID,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    OFFICIAL_SOURCE_REVISION,
    build_cogvideox15_i2v_command,
)
from studio.engine_adapters import build_cogvideox15_i2v_runtime_config
from studio.engine_registry import catalog_engines_for, get_catalog_engine


def test_catalog_entry_is_explicit_and_not_runtime_verified():
    engine = get_catalog_engine(ENGINE_ID)
    assert engine.version_family == "1.5-5b-i2v"
    assert engine.capabilities == ("video_generation",)
    assert engine.license == "CogVideoX License"
    assert engine.commercial_use_review_required is True
    assert engine.runtime_verified is False
    assert engine.checkpoint_verified is False
    assert engine.official_source == "https://github.com/zai-org/CogVideo"
    assert engine in catalog_engines_for("video_generation")


def test_command_binds_real_studio_inputs(tmp_path: Path):
    command = build_cogvideox15_i2v_command(
        python_executable="python",
        repository=tmp_path / "CogVideo",
        model_path=tmp_path / "CogVideoX1.5-5B-I2V",
        prompt="Yeti jumps over a moonberry bush",
        image_path=tmp_path / "yeti.webp",
        output_token="{output}",
    )
    assert command[:2] == ("python", "scripts/run_cogvideox15_i2v.py")
    assert "--repository" in command
    assert "--model-path" in command
    assert "--image" in command
    assert "{prompt}" not in command
    assert "Yeti jumps over a moonberry bush" in command
    assert "{output}" in command
    assert "--sequential-cpu-offload" in command


def test_runtime_config_uses_dynamic_image_and_prompt_tokens(tmp_path: Path):
    config = build_cogvideox15_i2v_runtime_config(
        repository=tmp_path / "CogVideo",
        model_path=tmp_path / "CogVideoX1.5-5B-I2V",
        output_path=str(tmp_path / "renders" / "shot.mp4"),
    )
    assert config.engine_id == ENGINE_ID
    assert "{prompt}" in config.command
    assert "{image_path}" in config.command
    assert "{output}" in config.command
    assert config.working_directory == str((tmp_path / "CogVideo").resolve())
    assert config.timeout_seconds == 21600


def test_frame_count_must_match_official_8n_plus_1_contract(tmp_path: Path):
    with pytest.raises(ValueError, match=r"8N\+1"):
        build_cogvideox15_i2v_command(
            python_executable="python",
            repository=tmp_path / "CogVideo",
            model_path=tmp_path / "model",
            prompt="test",
            image_path=tmp_path / "image.webp",
            output_token="{output}",
            num_frames=80,
        )


def test_provenance_constants_are_pinned():
    assert OFFICIAL_SOURCE_REVISION == "7a1af7154511e0ce4e4be8d62faa8c5e5a3532d2"
    assert MODEL_REVISION == "e724b279e89c204de20b66d8c09317a5d0d1b6f6"
    assert MODEL_REPOSITORY == "https://huggingface.co/zai-org/CogVideoX1.5-5B-I2V"
