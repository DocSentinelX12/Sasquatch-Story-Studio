from pathlib import Path

import pytest

from studio.engine_adapters import build_ltx25_runtime_config
from studio.ltx25_runtime import (
    DEFAULT_HEIGHT,
    DEFAULT_NUM_FRAMES,
    DEFAULT_WIDTH,
    LICENSE_NAME,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    SOURCE_REVISION,
    TRANSFORMER_FILENAME,
    build_ltx25_command,
    validate_dimensions,
)


def test_ltx25_source_and_model_provenance_contract_is_explicit():
    assert SOURCE_REVISION == "598ab41247a77dbfe29b5186e915bcf4f9040ec7"
    assert MODEL_REPOSITORY == "Lightricks/LTX-2.5"
    assert MODEL_REVISION is None
    assert LICENSE_NAME == "LTX-2.x Community License Agreement"
    assert TRANSFORMER_FILENAME == "ltx-2.5-22b-distilled-transformer-bf16.safetensors"


def test_ltx25_frame_and_resolution_contract():
    validate_dimensions(height=DEFAULT_HEIGHT, width=DEFAULT_WIDTH, num_frames=DEFAULT_NUM_FRAMES)
    with pytest.raises(ValueError, match="multiples of 32"):
        validate_dimensions(height=545, width=DEFAULT_WIDTH, num_frames=DEFAULT_NUM_FRAMES)
    with pytest.raises(ValueError, match="8N\+1"):
        validate_dimensions(height=DEFAULT_HEIGHT, width=DEFAULT_WIDTH, num_frames=120)


def test_ltx25_command_binds_real_studio_inputs(tmp_path: Path):
    studio_root = tmp_path / "studio"
    bridge = studio_root / "scripts" / "run_ltx25.py"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("# test bridge\n", encoding="utf-8")
    command = build_ltx25_command(
        python_executable="python",
        studio_root=studio_root,
        source_repository=(tmp_path / "LTX-2").resolve(),
        model_root=(tmp_path / "models" / "LTX-2.5").resolve(),
        prompt="make the Sasquatch bounce",
        image_path="{image_path}",
        output_token="{output}",
    )
    assert command[0] == "python"
    assert command[1] == str(bridge)
    assert "--repository" in command
    assert "--model-root" in command
    assert "{prompt}" in command
    assert "{image_path}" in command
    assert "{output}" in command
    assert str(DEFAULT_NUM_FRAMES) in command


def test_ltx25_production_runtime_config_preserves_dynamic_shot_inputs(tmp_path: Path):
    studio_root = tmp_path / "studio"
    bridge = studio_root / "scripts" / "run_ltx25.py"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("# test bridge\n", encoding="utf-8")
    config = build_ltx25_runtime_config(
        studio_root=studio_root,
        source_repository=tmp_path / "LTX-2",
        model_root=tmp_path / "models" / "LTX-2.5",
        output_path=str(tmp_path / "renders" / "shot.mp4"),
    )
    assert config.engine_id == "ltx-2.5"
    assert "{prompt}" in config.command
    assert "{image_path}" in config.command
    assert "{output}" in config.command
    assert config.working_directory == str(studio_root.resolve())
