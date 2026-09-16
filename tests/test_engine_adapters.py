import hashlib
import sys
from pathlib import Path

import pytest

from studio.engine_adapters import (
    VerifiedEngineRuntimeConfig,
    build_hunyuan_runtime_config,
    build_skyreels_r2v_runtime_config,
    build_verified_engine_adapter,
)
from studio.engine_registry import EngineVerificationRecord, RuntimeEngineRegistry, SQLiteEngineVerificationStore
from studio.production import ProductionRequest


def _registry(tmp_path: Path) -> RuntimeEngineRegistry:
    store = SQLiteEngineVerificationStore(tmp_path / "engines.sqlite")
    checkpoint = tmp_path / "checkpoint.bin"
    output = tmp_path / "verified.bin"
    checkpoint.write_bytes(b"real checkpoint fixture")
    output.write_bytes(b"real runtime output fixture")
    store.save(
        EngineVerificationRecord(
            engine_id="wan2.2",
            engine_version="2.2-test",
            executable=sys.executable,
            version_observation="test-runtime",
            checkpoint_path=str(checkpoint),
            checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            license_source="test fixture license source",
            license_evidence="test fixture only",
            runtime_output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            recorded_at=1,
            source_revision="test-source-revision",
        )
    )
    return RuntimeEngineRegistry(store)


def test_verified_engine_becomes_real_process_adapter(tmp_path: Path):
    registry = _registry(tmp_path)
    output = tmp_path / "render.txt"
    config = VerifiedEngineRuntimeConfig(
        engine_id="wan2.2",
        command=(
            sys.executable,
            "-c",
            "from pathlib import Path; Path(__import__('sys').argv[1]).write_text('engine output', encoding='utf-8')",
            "{output}",
        ),
        output_path=str(output),
        working_directory=str(tmp_path),
    )

    adapter = build_verified_engine_adapter(registry, config)
    response = adapter.execute(ProductionRequest("animate", {}, "a" * 64))

    assert output.read_text(encoding="utf-8") == "engine output"
    assert response.adapter_id == "wan2.2"
    assert response.provenance["engine_id"] == "wan2.2"
    assert response.provenance["quality_tier"] == "very_high"
    assert response.provenance["verified_source_revision"] == "test-source-revision"
    assert response.provenance["verified_checkpoint_sha256"] == hashlib.sha256((tmp_path / "checkpoint.bin").read_bytes()).hexdigest()


def test_hunyuan_runtime_config_is_wired_to_dynamic_shot_inputs(tmp_path: Path):
    config = build_hunyuan_runtime_config(
        repository=tmp_path / "HunyuanVideo-1.5",
        model_path=tmp_path / "ckpts",
        output_path=str(tmp_path / "renders" / "shot.mp4"),
    )
    assert config.engine_id == "hunyuanvideo-1.5"
    assert config.command[:3] == ("torchrun", "--nproc_per_node=1", "generate.py")
    assert "{prompt}" in config.command
    assert "{image_path}" in config.command
    assert "{output}" in config.command
    assert config.working_directory == str((tmp_path / "HunyuanVideo-1.5").resolve())


def test_skyreels_runtime_config_is_wired_to_dynamic_shot_inputs(tmp_path: Path):
    config = build_skyreels_r2v_runtime_config(
        repository=tmp_path / "SkyReels-V3",
        model_path=tmp_path / "SkyReels-V3-R2V-14B",
        output_path=str(tmp_path / "renders" / "shot.mp4"),
    )
    assert config.engine_id == "skyreels-v3-r2v-14b"
    assert config.command[:2] == ("python", "scripts/run_skyreels_v3_r2v.py")
    assert "{prompt}" in config.command
    assert "{reference_images}" in config.command
    assert "{output}" in config.command
    assert config.working_directory == str((tmp_path / "SkyReels-V3").resolve())


def test_process_adapter_binds_prompt_and_image_request_values(tmp_path: Path):
    registry = _registry(tmp_path)
    output = tmp_path / "render.txt"
    config = VerifiedEngineRuntimeConfig(
        engine_id="wan2.2",
        command=(
            sys.executable,
            "-c",
            "from pathlib import Path; Path(__import__('sys').argv[3]).write_text(__import__('sys').argv[1] + '|' + __import__('sys').argv[2], encoding='utf-8')",
            "{prompt}",
            "{image_path}",
            "{output}",
        ),
        output_path=str(output),
        working_directory=str(tmp_path),
    )
    adapter = build_verified_engine_adapter(registry, config)
    image = tmp_path / "reference.webp"
    image.write_bytes(b"image")

    adapter.execute(
        ProductionRequest(
            "animate",
            {"prompt": "make the character bounce", "image_path": str(image)},
            "b" * 64,
        )
    )

    assert output.read_text(encoding="utf-8") == f"make the character bounce|{image.resolve()}"


def test_process_adapter_binds_multiple_reference_images(tmp_path: Path):
    registry = _registry(tmp_path)
    output = tmp_path / "render.txt"
    config = VerifiedEngineRuntimeConfig(
        engine_id="wan2.2",
        command=(
            sys.executable,
            "-c",
            "from pathlib import Path; Path(__import__('sys').argv[2]).write_text(__import__('sys').argv[1], encoding='utf-8')",
            "{reference_images}",
            "{output}",
        ),
        output_path=str(output),
        working_directory=str(tmp_path),
    )
    adapter = build_verified_engine_adapter(registry, config)
    first = tmp_path / "reference-1.png"
    second = tmp_path / "reference-2.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    adapter.execute(
        ProductionRequest(
            "animate",
            {"reference_images": [str(first), str(second)]},
            "c" * 64,
        )
    )

    assert output.read_text(encoding="utf-8") == f"{first.resolve()},{second.resolve()}"


def test_unverified_engine_cannot_be_wired(tmp_path: Path):
    registry = RuntimeEngineRegistry(SQLiteEngineVerificationStore(tmp_path / "engines.sqlite"))
    config = VerifiedEngineRuntimeConfig(
        engine_id="wan2.2",
        command=(sys.executable, "-c", "pass", "{output}"),
        output_path=str(tmp_path / "render.txt"),
    )

    with pytest.raises(KeyError, match="no persisted runtime verification"):
        build_verified_engine_adapter(registry, config)


def test_runtime_command_must_explicitly_bind_output():
    with pytest.raises(ValueError, match="output"):
        VerifiedEngineRuntimeConfig(
            engine_id="wan2.2",
            command=(sys.executable, "-c", "pass"),
            output_path="render.mp4",
        )
