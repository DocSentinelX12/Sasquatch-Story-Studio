from pathlib import Path

from studio.resources import ComputeResource, PowerResource, PowerSourceKind, ResourceSnapshot, StorageResource
from studio.scheduler import Job, JobRequirements, JobState, Scheduler, SQLiteSchedulerStore


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
