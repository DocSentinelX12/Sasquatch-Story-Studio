import pytest

from studio.shutdown import ShutdownCoordinator, WorkerDrainState


def test_shutdown_drains_without_starting_new_work():
    coordinator = ShutdownCoordinator()
    decision = coordinator.request_drain("power reserve low")
    assert decision.state == WorkerDrainState.DRAINING
    assert decision.finish_current_job
    assert not decision.start_new_jobs


def test_shutdown_reaches_drained_only_at_checkpoint_boundary():
    coordinator = ShutdownCoordinator()
    coordinator.request_drain()
    decision = coordinator.checkpoint_completed()
    assert decision.state == WorkerDrainState.DRAINED
    assert not decision.finish_current_job


def test_shutdown_requires_drain_before_checkpoint_completion():
    with pytest.raises(RuntimeError):
        ShutdownCoordinator().checkpoint_completed()


def test_restart_returns_worker_to_running_for_lease_recovery():
    coordinator = ShutdownCoordinator()
    coordinator.request_drain()
    coordinator.checkpoint_completed()
    decision = coordinator.recovery_after_restart()
    assert decision.state == WorkerDrainState.RUNNING
    assert decision.start_new_jobs
