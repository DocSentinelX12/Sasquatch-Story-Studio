import pytest

from studio.coordinator import ProductionCoordinator
from studio.resources import ComputeResource, ResourceSnapshot
from studio.scheduler import JobRequirements, JobState, Scheduler


def resource():
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


def test_coordinator_leases_and_completes_stage_job():
    scheduler = Scheduler()
    coordinator = ProductionCoordinator(scheduler)
    job = coordinator.submit_stage("ep-001", "animate", JobRequirements(slots=1))
    leased = coordinator.lease("worker-1", resource(), ResourceSnapshot(compute=(resource(),), power=()), now=10)
    assert leased.id == job.id
    coordinator.complete(leased.id, "worker-1", "artifact://shot-001")
    assert scheduler.snapshot()[0].state == JobState.COMPLETED


def test_coordinator_rejects_unknown_stage():
    coordinator = ProductionCoordinator(Scheduler())
    with pytest.raises(ValueError):
        coordinator.submit_stage("ep-001", "not-a-stage", JobRequirements())


def test_coordinator_requeues_expired_leases():
    scheduler = Scheduler()
    coordinator = ProductionCoordinator(scheduler)
    coordinator.submit_stage("ep-001", "animate", JobRequirements())
    coordinator.lease("worker-1", resource(), ResourceSnapshot(compute=(resource(),), power=()), now=10, lease_seconds=5)
    assert coordinator.recover(15) == ("ep-001:animate",)
    assert scheduler.snapshot()[0].state == JobState.QUEUED
