from pathlib import Path

import pytest

from studio.engine_registry import get_catalog_engine
from studio.skyreels_v3_runtime import build_skyreels_r2v_command


def test_skyreels_r2v_command_matches_official_local_inference_contract(tmp_path: Path):
    repository = tmp_path / "SkyReels-V3"
    model_path = tmp_path / "SkyReels-V3-R2V-14B"
    reference = tmp_path / "meta-reference.png"

    command = build_skyreels_r2v_command(
        python_executable="python",
        repository=repository,
        model_path=model_path,
        prompt="A friendly Sasquatch walks through a moonlit forest.",
        reference_images=(reference,),
        output_token="{output}",
        seed=42,
        duration=5,
        resolution="720P",
        offload=True,
        low_vram=False,
    )

    assert command[:2] == ("python", "scripts/run_skyreels_v3_r2v.py")
    assert command[command.index("--model-path") + 1] == str(model_path.resolve())
    assert command[command.index("--repository") + 1] == str(repository.resolve())
    assert command[command.index("--ref-imgs") + 1] == str(reference.resolve())
    assert command[command.index("--prompt") + 1] == "A friendly Sasquatch walks through a moonlit forest."
    assert command[command.index("--output") + 1] == "{output}"
    assert command[command.index("--duration") + 1] == "5"
    assert command[command.index("--resolution") + 1] == "720P"
    assert "--offload" in command
    assert "--low-vram" not in command
    assert all("http://" not in item and "https://" not in item for item in command)


def test_skyreels_r2v_command_rejects_more_than_four_reference_images(tmp_path: Path):
    references = tuple(tmp_path / f"reference-{index}.png" for index in range(5))
    with pytest.raises(ValueError, match="1 to 4 reference images"):
        build_skyreels_r2v_command(
            python_executable="python",
            repository=tmp_path / "SkyReels-V3",
            model_path=tmp_path / "SkyReels-V3-R2V-14B",
            prompt="verification prompt",
            reference_images=references,
            output_token="{output}",
            seed=1,
        )


def test_skyreels_r2v_catalog_entry_is_video_only_and_license_gated():
    engine = get_catalog_engine("skyreels-v3-r2v-14b")
    assert engine.version_family == "3-r2v-14b"
    assert engine.capabilities == ("video_generation",)
    assert engine.license == "Skywork Community License"
    assert engine.commercial_use_review_required is True
    assert engine.official_source == "https://github.com/SkyworkAI/SkyReels-V3"
