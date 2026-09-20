from pathlib import Path
import hashlib

import pytest

from studio.distributed_execution import DistributedLaunchSpec
from studio.engine_adapters import VerifiedEngineRuntimeConfig, build_verified_engine_adapter
from studio.engine_registry import EngineVerificationRecord, RuntimeEngineRegistry, SQLiteEngineVerificationStore
from studio.production import ProductionRequest
from studio.verified_distributed_runtime import build_verified_distributed_launch_spec
from studio.wan22_runtime import build_wan22_command


def _adapter(tmp_path: Path, *, distributed: bool, launch_mode: str | None = None):
    checkpoint = tmp_path / "checkpoint.bin"
    runtime = tmp_path / "runtime.bin"
    checkpoint.write_bytes(b"checkpoint")
    runtime.write_bytes(b"runtime")
    digest = hashlib.sha256(runtime.read_bytes()).hexdigest()
    record = EngineVerificationRecord(
        engine_id="wan2.2",
        engine_version="2.2-test",
        executable="python",
        version_observation="test",
        checkpoint_path=str(checkpoint),
        checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        license_source="test",
        license_evidence="test",
        runtime_output_sha256=digest,
        recorded_at=1,
        source_revision="source",
        distributed_execution_verified=distributed,
        distributed_launch_mode=launch_mode if distributed else None,
        distributed_runtime_output_sha256=digest if distributed else None,
    )
    store = SQLiteEngineVerificationStore(tmp_path / "engines.sqlite")
    store.save(record)
    registry = RuntimeEngineRegistry(store)
    adapter = build_verified_engine_adapter(
        registry,
        VerifiedEngineRuntimeConfig(
            engine_id="wan2.2",
            command=build_wan22_command(
                python_executable="python",
                repository=tmp_path,
                model_path=tmp_path / "model",
                prompt="{prompt}",
                output_token="{output}",
            ),
            output_path=str(tmp_path / "out.mp4"),
            working_directory=str(tmp_path),
        ),
    )
    return registry, adapter


def _allocation(world_size: int = 2):
    return type(
        "Allocation",
        (),
        {
            "worker_ids": ("worker-a", "worker-b"),
            "node_count": 2,
            "world_size": world_size,
        },
    )()


def test_requires_explicit_distributed_verification(tmp_path: Path):
    registry, adapter = _adapter(tmp_path, distributed=False)
    with pytest.raises(RuntimeError, match="distributed execution verification"):
        build_verified_distributed_launch_spec(
            registry,
            adapter,
            ProductionRequest("animate", {"prompt": "bounce"}, "a" * 64),
            _allocation(),
            "rdzv",
            "10.0.0.1",
            29500,
        )


def test_builds_wan22_verified_multi_node_command(tmp_path: Path):
    registry, adapter = _adapter(tmp_path, distributed=True, launch_mode="torchrun_wan22")
    spec = build_verified_distributed_launch_spec(
        registry,
        adapter,
        ProductionRequest("animate", {"prompt": "bounce"}, "b" * 64),
        _allocation(8),
        "rdzv",
        "10.0.0.1",
        29500,
    )
    assert isinstance(spec, DistributedLaunchSpec)
    assert spec.executable == "torchrun"
    assert spec.command[0] == "generate.py"
    assert "--dit_fsdp" in spec.command
    assert "--t5_fsdp" in spec.command
    assert spec.command[-2:] == ("--ulysses_size", "8")
    assert "--offload_model" not in spec.command
    assert "--prompt" in spec.command
    assert spec.command[spec.command.index("--prompt") + 1] == "bounce"
    assert spec.command[spec.command.index("--save_file") + 1] == "{output}"
    assert spec.output_path == str((tmp_path / "out.mp4").resolve())


def test_rejects_unsupported_distributed_engine_contract(tmp_path: Path):
    registry, adapter = _adapter(tmp_path, distributed=True, launch_mode="torchrun")
    with pytest.raises(ValueError, match="torchrun_wan22"):
        build_verified_distributed_launch_spec(
            registry,
            adapter,
            ProductionRequest("animate", {"prompt": "bounce"}, "c" * 64),
            _allocation(),
            "rdzv",
            "10.0.0.1",
            29500,
        )


def test_rejects_invalid_wan22_world_size(tmp_path: Path):
    registry, adapter = _adapter(tmp_path, distributed=True, launch_mode="torchrun_wan22")
    with pytest.raises(ValueError, match="divide its 40 attention heads"):
        build_verified_distributed_launch_spec(
            registry,
            adapter,
            ProductionRequest("animate", {"prompt": "bounce"}, "d" * 64),
            _allocation(6),
            "rdzv",
            "10.0.0.1",
            29500,
        )


def test_persisted_distributed_evidence_round_trips(tmp_path: Path):
    registry, _ = _adapter(tmp_path, distributed=True, launch_mode="torchrun_wan22")
    record = registry.store.load("wan2.2")
    assert record is not None
    assert record.distributed_execution_verified is True
    assert record.distributed_launch_mode == "torchrun_wan22"
    assert record.distributed_runtime_output_sha256 is not None
    assert len(record.distributed_runtime_output_sha256) == 64
