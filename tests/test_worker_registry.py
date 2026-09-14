import pytest

from studio.resources import ComputeResource
from studio.worker_registry import SQLiteWorkerRegistryStore, WorkerRecord, WorkerRegistry, WorkerState


def worker() -> WorkerRecord:
    return WorkerRecord(
        id="worker-a",
        resource=ComputeResource(
            id="resource-a",
            cpu_cores=16,
            memory_bytes=32 * 1024**3,
            gpu_count=1,
            gpu_models=("observed-gpu",),
            vram_bytes=24 * 1024**3,
            capabilities=("video", "cuda"),
            installed_engines=("observed-engine",),
            logical_slots=4,
            scratch_bytes=100 * 1024**3,
        ),
        state=WorkerState.VERIFIED_AVAILABLE,
        observed_at=123,
        observation_source="worker-heartbeat",
        quota_note="",
    )


def test_register_update_and_snapshot():
    registry = WorkerRegistry()
    record = worker()
    registry.register(record)
    assert registry.get("worker-a") == record
    updated = WorkerRecord(record.id, record.resource, WorkerState.VERIFIED_LIMITED, 456, "quota-observation", "limited")
    registry.update(updated)
    assert registry.snapshot() == (updated,)


def test_rejects_empty_id_and_duplicate():
    with pytest.raises(ValueError):
        WorkerRecord("", worker().resource)
    registry = WorkerRegistry((worker(),))
    with pytest.raises(ValueError):
        registry.register(worker())


def test_unavailable_preserves_observed_resource():
    registry = WorkerRegistry((worker(),))
    updated = registry.mark_unavailable("worker-a", WorkerState.OFFLINE, observed_at=999)
    assert updated.state == WorkerState.OFFLINE
    assert updated.resource == worker().resource
    assert updated.observed_at == 999


def test_sqlite_round_trip(tmp_path):
    registry = WorkerRegistry((worker(),))
    store = SQLiteWorkerRegistryStore(tmp_path / "workers.sqlite")
    store.save(registry)
    restored = store.load()
    assert restored.snapshot() == registry.snapshot()


def test_unavailable_requires_unavailable_state():
    registry = WorkerRegistry((worker(),))
    with pytest.raises(ValueError):
        registry.mark_unavailable("worker-a", WorkerState.VERIFIED_AVAILABLE)
