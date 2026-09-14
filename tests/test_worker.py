import pytest

from studio.resources import ComputeResource
from studio.scheduler import JobRequirements, JobState, Scheduler
from studio.worker import WorkerCoordinator, WorkerResult, WorkerResultState, WorkerTask


def test_worker_task_rejects_mismatched_inputs():
    with pytest.raises(ValueError):
        WorkerTask("t", "ep", "animate", "shot", ("a",), (), JobRequirements())


def test_result_has_explicit_state():
    result = WorkerResult("t", WorkerResultState.FAILED, error="worker lost")
    assert result.state == WorkerResultState.FAILED
    assert result.error == "worker lost"


def test_worker_coordinator_uses_existing_lease_and_recovery():
    scheduler = Scheduler()
    scheduler.submit(__import__("studio.scheduler", fromlist=["Job"]).Job("t", JobRequirements()))
    resource = ComputeResource("r", 8, 16 * 1024**3, logical_slots=2)
    leased = scheduler.choose_on_worker("w1", resource, 0, now=10, lease_seconds=5)
    assert leased is not None
    coordinator = WorkerCoordinator(scheduler)
    assert coordinator.recover(15) == ("t",)
    leased = scheduler.choose_on_worker("w2", resource, 0, now=16, lease_seconds=5)
    assert leased is not None
    coordinator.complete("t", "w2")
    assert scheduler.snapshot()[0].state == JobState.COMPLETED
