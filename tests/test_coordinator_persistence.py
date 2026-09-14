from studio.coordinator import CoordinatorStore, ProductionCoordinator
from studio.scheduler import JobRequirements, JobState, SQLiteSchedulerStore, Scheduler


def test_coordinator_persists_stage_output_and_canonical_hash(tmp_path):
    scheduler_path = tmp_path / "scheduler.sqlite"
    coordinator_path = tmp_path / "coordinator.sqlite"

    scheduler = Scheduler()
    scheduler_store = SQLiteSchedulerStore(scheduler_path)
    store = CoordinatorStore(coordinator_path)
    coordinator = ProductionCoordinator(scheduler, store=store)

    coordinator.submit_stage(
        "ep-001",
        "animate",
        JobRequirements(slots=1),
        canonical_source_hash="a" * 64,
    )
    scheduler_store.save(scheduler)
    coordinator.lease(
        "worker-1",
        _resource(),
        _snapshot(),
        now=10,
    )
    completed = coordinator.complete("ep-001:animate", "worker-1", "artifact://shot-001")
    scheduler_store.save(scheduler)
    assert completed.output_ref == "artifact://shot-001"

    restored_scheduler = scheduler_store.load()
    restored = ProductionCoordinator(restored_scheduler, store=CoordinatorStore(coordinator_path))
    stage_job = restored.stage_for("ep-001:animate")
    assert restored_scheduler.snapshot()[0].state == JobState.COMPLETED
    assert stage_job.canonical_source_hash == "a" * 64
    assert stage_job.output_ref == "artifact://shot-001"


def _resource():
    from studio.resources import ComputeResource

    return ComputeResource(
        "worker-resource",
        8,
        16 * 1024**3,
        gpu_count=1,
        vram_bytes=12 * 1024**3,
        logical_slots=4,
        healthy=True,
        scratch_bytes=20 * 1024**3,
    )


def _snapshot():
    from studio.resources import ResourceSnapshot

    resource = _resource()
    return ResourceSnapshot(compute=(resource,), power=())
