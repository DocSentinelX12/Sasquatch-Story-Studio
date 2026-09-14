from pathlib import Path

from studio.resources import ComputeResource, PowerResource, PowerSourceKind, ResourceSnapshot, StorageResource
from studio.scheduler import Job, JobRequirements, JobState, Scheduler, SQLiteSchedulerStore
from studio.workers import SQLiteWorkerStore, Worker, WorkerHeartbeat, WorkerRegistry


def snapshot():
    return ResourceSnapshot(
        compute=(ComputeResource("gpu-1", 32, 64 * 1024**3, gpu_count=1, vram_bytes=24 * 1024**3, capabilities=("video_generation",), installed_engines=("wan2.2",), logical_slots=40, power_budget_watts=700, scratch_bytes=2 * 1024**12),),
        storage=(StorageResource("nvme-1", 4 * 1024**12, 3 * 1024**12, "hot"),),
        power=(PowerResource("grid-1", PowerSourceKind.GRID, 3000, 2500),),
    )


def test_capacity_is_observed_not_invented():
    resources = snapshot()
    assert resources.healthy_compute_slots == 40
    assert resources.healthy_power_watts == 2500
    assert resources.free_storage_bytes == 3 * 1024**12


def test_scheduler_uses_shared_pool_and_recovers_expired_lease():
    scheduler = Scheduler([Job("video-1", JobRequirements(slots=2, vram_bytes=8 * 1024**3, power_watts=500, capabilities=("video_generation",), engines=("wan2.2",)), priority=10)])
    leased = scheduler.choose("worker-a", snapshot(), now=100, lease_seconds=10)
    assert leased is not None
    assert leased.state == JobState.LEASED
    assert leased.lease_owner == "worker-a"
    assert scheduler.recover_expired(110) == ("video-1",)
    assert scheduler.snapshot()[0].state == JobState.QUEUED


def test_scheduler_rejects_missing_real_capacity():
    scheduler = Scheduler([Job("video-2", JobRequirements(vram_bytes=32 * 1024**3, engines=("wan2.2",)))])
    assert scheduler.choose("worker-a", snapshot(), now=100) is None


def test_scheduler_does_not_overbook_shared_slots_or_power():
    scheduler = Scheduler([
        Job("video-a", JobRequirements(slots=30, power_watts=1600), priority=10),
        Job("video-b", JobRequirements(slots=20, power_watts=1000), priority=9),
    ])
    assert scheduler.choose("worker-a", snapshot(), now=100) is not None
    assert scheduler.choose("worker-b", snapshot(), now=100) is None


def test_scheduler_worker_specific_capacity_is_enforced():
    scheduler = Scheduler([Job("video-gpu", JobRequirements(slots=2, vram_bytes=16 * 1024**3, capabilities=("video_generation",), engines=("wan2.2",)))])
    cpu_worker = ComputeResource("cpu-1", 16, 32 * 1024**3, capabilities=("animation",), logical_slots=8)
    gpu_worker = ComputeResource("gpu-2", 16, 32 * 1024**3, gpu_count=1, vram_bytes=24 * 1024**3, capabilities=("video_generation",), installed_engines=("wan2.2",), logical_slots=8)
    assert scheduler.choose_on_worker("cpu-1", cpu_worker, pool_power_watts=2000, now=100) is None
    assert scheduler.choose_on_worker("gpu-2", gpu_worker, pool_power_watts=2000, now=100) is not None


def test_scheduler_worker_specific_capacity_accounts_for_existing_leases():
    scheduler = Scheduler([
        Job("video-a", JobRequirements(slots=6, memory_bytes=8 * 1024**3), priority=10),
        Job("video-b", JobRequirements(slots=6, memory_bytes=8 * 1024**3), priority=9),
    ])
    worker = ComputeResource("gpu-1", 16, 16 * 1024**3, gpu_count=1, vram_bytes=24 * 1024**3, logical_slots=8, scratch_bytes=20 * 1024**3)
    assert scheduler.choose_on_worker("worker-a", worker, pool_power_watts=2000, now=100) is not None
    assert scheduler.choose_on_worker("worker-a", worker, pool_power_watts=2000, now=100) is None
    assert scheduler.choose_on_worker("worker-b", worker, pool_power_watts=2000, now=100) is not None


def test_scheduler_worker_specific_power_is_checked_against_existing_leases():
    scheduler = Scheduler([
        Job("video-a", JobRequirements(power_watts=1200), priority=10),
        Job("video-b", JobRequirements(power_watts=1000), priority=9),
    ])
    worker = snapshot().compute[0]
    assert scheduler.choose_on_worker("worker-a", worker, pool_power_watts=1500, now=100) is not None
    assert scheduler.choose_on_worker("worker-b", worker, pool_power_watts=1500, now=100) is None


def test_scheduler_persists_and_restores_leases(tmp_path: Path):
    db = tmp_path / "scheduler.sqlite3"
    store = SQLiteSchedulerStore(db)
    original = Scheduler([Job("video-3", JobRequirements(vram_bytes=8 * 1024**3), priority=7)])
    leased = original.choose("worker-a", snapshot(), now=100, lease_seconds=900)
    assert leased is not None
    store.save(original)

    restored = store.load()
    assert restored.snapshot() == original.snapshot()
    restored.complete("video-3", "worker-a")
    store.save(restored)
    assert store.load().snapshot()[0].state == JobState.COMPLETED


def test_scheduler_persistence_survives_expired_lease_recovery(tmp_path: Path):
    store = SQLiteSchedulerStore(tmp_path / "scheduler.sqlite3")
    scheduler = Scheduler([Job("video-4", JobRequirements())])
    assert scheduler.choose("worker-a", snapshot(), now=100, lease_seconds=10) is not None
    store.save(scheduler)

    restored = store.load()
    assert restored.recover_expired(110) == ("video-4",)
    store.save(restored)
    assert store.load().snapshot()[0].state == JobState.QUEUED


def test_worker_heartbeat_is_monotonic_and_stale_workers_are_excluded():
    worker = Worker("worker-a", snapshot().compute[0], WorkerHeartbeat("worker-a", 100))
    registry = WorkerRegistry([worker])
    registry.heartbeat(WorkerHeartbeat("worker-a", 120, utilization_percent=50))
    assert registry.stale_worker_ids(125, 10) == ()
    assert registry.stale_worker_ids(131, 10) == ("worker-a",)
    assert registry.healthy_resources(now=131, max_age_seconds=10) == ()


def test_worker_rejects_older_heartbeat():
    worker = Worker("worker-a", snapshot().compute[0], WorkerHeartbeat("worker-a", 100))
    registry = WorkerRegistry([worker])
    try:
        registry.heartbeat(WorkerHeartbeat("worker-a", 99))
    except ValueError as exc:
        assert "backwards" in str(exc)
    else:
        raise AssertionError("older heartbeat must be rejected")


def test_worker_registry_persists_resources_and_heartbeat(tmp_path: Path):
    store = SQLiteWorkerStore(tmp_path / "workers.sqlite3")
    worker = Worker(
        "worker-a",
        snapshot().compute[0],
        WorkerHeartbeat("worker-a", observed_at=123, active_job_ids=("video-1",), thermal_celsius=62.5, utilization_percent=91.0),
    )
    registry = WorkerRegistry([worker])
    store.save(registry)

    restored = store.load()
    assert restored.snapshot() == registry.snapshot()
    assert restored.healthy_resources() == (worker.resource,)


def test_worker_heartbeat_persists_health_state(tmp_path: Path):
    store = SQLiteWorkerStore(tmp_path / "workers.sqlite3")
    worker = Worker("worker-a", snapshot().compute[0], WorkerHeartbeat("worker-a", 10))
    registry = WorkerRegistry([worker])
    registry.heartbeat(WorkerHeartbeat("worker-a", 20, healthy=False, utilization_percent=100))
    store.save(registry)

    restored = store.load()
    assert restored.snapshot()[0].heartbeat.healthy is False
    assert restored.healthy_resources() == ()


def test_worker_lookup_returns_observed_worker():
    worker = Worker("worker-a", snapshot().compute[0], WorkerHeartbeat("worker-a", 10))
    registry = WorkerRegistry([worker])
    assert registry.get("worker-a") == worker
