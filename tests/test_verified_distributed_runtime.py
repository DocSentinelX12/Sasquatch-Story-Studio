from pathlib import Path
import hashlib

import pytest

from studio.distributed_execution import DistributedLaunchSpec
from studio.engine_adapters import VerifiedEngineRuntimeConfig, build_verified_engine_adapter
from studio.engine_registry import EngineVerificationRecord, RuntimeEngineRegistry, SQLiteEngineVerificationStore
from studio.production import ProductionRequest
from studio.verified_distributed_runtime import build_verified_distributed_launch_spec


def _adapter(tmp_path: Path, *, distributed: bool):
    checkpoint = tmp_path / "checkpoint.bin"
    runtime = tmp_path / "runtime.bin"
    checkpoint.write_bytes(b"checkpoint")
    runtime.write_bytes(b"runtime")
    digest = hashlib.sha256(runtime.read_bytes()).hexdigest()
    record = EngineVerificationRecord(
        engine_id="wan2.2", engine_version="2.2-test", executable="python",
        version_observation="test", checkpoint_path=str(checkpoint),
        checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        license_source="test", license_evidence="test", runtime_output_sha256=digest,
        recorded_at=1, source_revision="source", distributed_execution_verified=distributed,
        distributed_launch_mode="torchrun" if distributed else None,
        distributed_runtime_output_sha256=digest if distributed else None,
    )
    store = SQLiteEngineVerificationStore(tmp_path / "engines.sqlite")
    store.save(record)
    registry = RuntimeEngineRegistry(store)
    adapter = build_verified_engine_adapter(registry, VerifiedEngineRuntimeConfig(
        engine_id="wan2.2",
        command=("python", "generate.py", "--prompt", "{prompt}", "--output", "{output}"),
        output_path=str(tmp_path / "out.mp4"), working_directory=str(tmp_path),
    ))
    return registry, adapter


def _allocation():
    return type("Allocation", (), {"worker_ids": ("worker-a", "worker-b"), "node_count": 2})()


def test_requires_explicit_distributed_verification(tmp_path: Path):
    registry, adapter = _adapter(tmp_path, distributed=False)
    with pytest.raises(RuntimeError, match="distributed execution verification"):
        build_verified_distributed_launch_spec(registry, adapter, ProductionRequest("animate", {"prompt": "bounce"}, "a" * 64), _allocation(), "rdzv", "10.0.0.1", 29500)


def test_derives_torchrun_application_from_verified_command(tmp_path: Path):
    registry, adapter = _adapter(tmp_path, distributed=True)
    spec = build_verified_distributed_launch_spec(registry, adapter, ProductionRequest("animate", {"prompt": "bounce"}, "b" * 64), _allocation(), "rdzv", "10.0.0.1", 29500)
    assert isinstance(spec, DistributedLaunchSpec)
    assert spec.executable == "torchrun"
    assert spec.command == ("generate.py", "--prompt", "bounce", "--output", "{output}")
    assert spec.output_path == str((tmp_path / "out.mp4").resolve())


def test_rejects_non_torchrun_verified_mode(tmp_path: Path):
    registry, adapter = _adapter(tmp_path, distributed=True)
    record = registry.store.load("wan2.2")
    assert record is not None
    from dataclasses import replace
    registry.store.save(replace(record, distributed_launch_mode="service"))
    with pytest.raises(ValueError, match="torchrun"):
        build_verified_distributed_launch_spec(registry, adapter, ProductionRequest("animate", {"prompt": "bounce"}, "c" * 64), _allocation(), "rdzv", "10.0.0.1", 29500)
