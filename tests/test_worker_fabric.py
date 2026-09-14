from dataclasses import dataclass

from studio.compute_broker import ComputeBroker, ProductionTask
from studio.resources import ComputeResource
from studio.scheduler import Job, JobRequirements, JobState, Scheduler
from studio.worker import WorkerResult, WorkerResultState, WorkerTask
from studio.worker_fabric import DispatchState, WorkerFabric
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


@dataclass
class FakeExecutor:
    result: WorkerResult

    def execute(self, task: WorkerTask) -> WorkerResult:
        return self.result


def record(worker_id: str, state=WorkerState.VERIFIED_AVAILABLE):
    return WorkerRecord(worker_id, ComputeResource(worker_id, 8, 16 * 1024**3, gpu_count=1, vram_bytes=8 * 1024**3, logical_slots=2, scratch_bytes=20 * 1024**3, power_budget_watts=300), state=state)


def factory(task, job, worker_id):
    return WorkerTask(task.id, "ep-1", "animate", "shot-1", ("input-a",), ("hash-a",), task.requirements, (("worker", worker_id),))


def test_completed_dispatch_marks_job_completed():
    scheduler = Scheduler()
    registry = WorkerRegistry((record("w1"),))
    task = ProductionTask("task-1", JobRequirements())
    broker = ComputeBroker(scheduler, registry)
    broker.submit(task)
    fabric = WorkerFabric(broker, {"w1": FakeExecutor(WorkerResult("task-1", WorkerResultState.COMPLETED, ("out-1",)))})

    result = fabric.dispatch(task, factory, now=100)

    assert result.state == DispatchState.COMPLETED
    assert result.output_refs == ("out-1",)
    assert scheduler.snapshot()[0].state == JobState.COMPLETED


def test_unavailable_worker_is_marked_and_job_requeued():
    scheduler = Scheduler()
    registry = WorkerRegistry((record("w1"), record("w2")))
    task = ProductionTask("task-2", JobRequirements())
    broker = ComputeBroker(scheduler, registry)
    broker.submit(task)
    fabric = WorkerFabric(broker, {"w1": FakeExecutor(WorkerResult("task-2", WorkerResultState.UNAVAILABLE, error="lost worker"))})

    result = fabric.dispatch(task, factory, now=100)

    assert result.state == DispatchState.REQUEUED
    assert scheduler.snapshot()[0].state == JobState.QUEUED
    assert registry.get("w1").state == WorkerState.TEMPORARILY_UNAVAILABLE


def test_executor_failure_is_terminal_and_not_silently_successful():
    scheduler = Scheduler()
    registry = WorkerRegistry((record("w1"),))
    task = ProductionTask("task-3", JobRequirements())
    broker = ComputeBroker(scheduler, registry)
    broker.submit(task)
    fabric = WorkerFabric(broker, {"w1": FakeExecutor(WorkerResult("task-3", WorkerResultState.FAILED, error="render failed"))})

    result = fabric.dispatch(task, factory, now=100)

    assert result.state == DispatchState.FAILED
    assert result.error == "render failed"
    assert scheduler.snapshot()[0].state == JobState.FAILED


def test_missing_executor_requeues_without_fake_completion():
    scheduler = Scheduler()
    registry = WorkerRegistry((record("w1"),))
    task = ProductionTask("task-4", JobRequirements())
    broker = ComputeBroker(scheduler, registry)
    broker.submit(task)

    result = WorkerFabric(broker, {}).dispatch(task, factory, now=100)

    assert result.state == DispatchState.REQUEUED
    assert scheduler.snapshot()[0].state == JobState.QUEUED
