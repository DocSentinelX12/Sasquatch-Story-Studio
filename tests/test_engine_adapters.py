import hashlib
import sys
from pathlib import Path

import pytest

from studio.engine_adapters import VerifiedEngineRuntimeConfig, build_verified_engine_adapter
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
