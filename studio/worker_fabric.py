"""Durable distributed worker execution and checkpoint-aware reassignment."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping

from .compute_broker import ComputeBroker, ProductionTask
from .scheduler import Job
from .worker import WorkerExecutor, WorkerResultState, WorkerTask
from .worker_registry import WorkerState


class DispatchState(StrEnum):
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"
    REQUEUED = "requeued"
    NO_WORKER = "no_worker"


@dataclass(frozen=True)
class DispatchRecord:
    task_id: str
    job_id: str
    worker_id: str | None
    state: DispatchState
    output_refs: tuple[str, ...] = ()
    error: str | None = None


class WorkerFabric:
    """Routes checkpointable tasks and recovers them when workers disappear."""

    def __init__(self, broker: ComputeBroker, executors: Mapping[str, WorkerExecutor]):
        self.broker = broker
        self.executors = dict(executors)

    def dispatch(self, task: ProductionTask, worker_task_factory: Callable[[ProductionTask, Job, str], WorkerTask], now: int, lease_seconds: int = 900) -> DispatchRecord:
        decision, job = self.broker.lease(task, now, lease_seconds)
        if job is None:
            return DispatchRecord(task.id, task.id, None, DispatchState.NO_WORKER, error=decision.reason)
        worker_id = job.lease_owner
        assert worker_id is not None
        executor = self.executors.get(worker_id)
        if executor is None:
            self.broker.scheduler.requeue(job.id, worker_id)
            return DispatchRecord(task.id, job.id, worker_id, DispatchState.REQUEUED, error="no executor registered for leased worker")
        worker_task = worker_task_factory(task, job, worker_id)
        result = executor.execute(worker_task)
        if result.task_id != task.id:
            self.broker.scheduler.fail(job.id, worker_id)
            return DispatchRecord(task.id, job.id, worker_id, DispatchState.FAILED, error="executor returned a mismatched task id")
        if result.state == WorkerResultState.COMPLETED:
            self.broker.scheduler.complete(job.id, worker_id)
            return DispatchRecord(task.id, job.id, worker_id, DispatchState.COMPLETED, result.output_refs)
        if result.state in (WorkerResultState.UNAVAILABLE, WorkerResultState.REJECTED):
            if result.state == WorkerResultState.UNAVAILABLE:
                self.broker.registry.mark_unavailable(worker_id, WorkerState.TEMPORARILY_UNAVAILABLE, result.error or "worker unavailable")
            self.broker.scheduler.requeue(job.id, worker_id)
            return DispatchRecord(task.id, job.id, worker_id, DispatchState.REQUEUED, error=result.error)
        self.broker.scheduler.fail(job.id, worker_id)
        return DispatchRecord(task.id, job.id, worker_id, DispatchState.FAILED, error=result.error)

    def recover_expired(self, now: int) -> tuple[str, ...]:
        return self.broker.scheduler.recover_expired(now)
