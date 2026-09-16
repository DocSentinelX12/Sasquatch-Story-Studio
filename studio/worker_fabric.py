"""Durable distributed worker execution and checkpoint-aware reassignment."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping, Protocol

from .compute_broker import ComputeBroker, ProductionTask
from .scheduler import Job
from .worker import WorkerExecutor, WorkerResultState, WorkerTask
from .worker_registry import WorkerState


class LeaseProvider(Protocol):
    def __call__(self, worker_id: str, task: WorkerTask, expires_at: int, now: int):
        ...


class LeaseBoundExecutor(Protocol):
    def execute_with_lease(self, task: WorkerTask, lease: object) -> object:
        ...


class DispatchState(StrEnum):
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
    """Routes checkpointable tasks and recovers them when workers disappear.

    Local executors retain the existing direct path. Remote executors must
    expose ``execute_with_lease`` and are given a control-plane-issued lease
    before any network execution is attempted.
    """

    def __init__(
        self,
        broker: ComputeBroker,
        executors: Mapping[str, WorkerExecutor],
        lease_provider: LeaseProvider | None = None,
    ):
        self.broker = broker
        self.executors = dict(executors)
        self.lease_provider = lease_provider

    def dispatch(
        self,
        task: ProductionTask,
        worker_task_factory: Callable[[ProductionTask, Job, str], WorkerTask],
        now: int,
        lease_seconds: int = 900,
    ) -> DispatchRecord:
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
        try:
            if hasattr(executor, "execute_with_lease"):
                if self.lease_provider is None:
                    self.broker.scheduler.requeue(job.id, worker_id)
                    return DispatchRecord(task.id, job.id, worker_id, DispatchState.REQUEUED, error="remote executor requires an authenticated lease provider")
                lease = self.lease_provider(worker_id, worker_task, job.lease_until or now, now)
                result = executor.execute_with_lease(worker_task, lease)  # type: ignore[attr-defined]
            else:
                result = executor.execute(worker_task)
        except (PermissionError, RuntimeError, ValueError, OSError) as exc:
            self.broker.scheduler.requeue(job.id, worker_id)
            return DispatchRecord(task.id, job.id, worker_id, DispatchState.REQUEUED, error=str(exc))
        if result.task_id != task.id:
            self.broker.scheduler.fail(job.id, worker_id)
            return DispatchRecord(task.id, job.id, worker_id, DispatchState.FAILED, error="executor returned a mismatched task id")
        if result.state == WorkerResultState.COMPLETED:
            self.broker.scheduler.complete(job.id, worker_id)
            return DispatchRecord(task.id, job.id, worker_id, DispatchState.COMPLETED, result.output_refs)
        if result.state in (WorkerResultState.UNAVAILABLE, WorkerResultState.REJECTED):
            if result.state == WorkerResultState.UNAVAILABLE:
                self.broker.registry.mark_unavailable(worker_id, WorkerState.TEMPORARILY_UNAVAILABLE, quota_note=result.error or "worker unavailable")
            self.broker.scheduler.requeue(job.id, worker_id)
            return DispatchRecord(task.id, job.id, worker_id, DispatchState.REQUEUED, error=result.error)
        self.broker.scheduler.fail(job.id, worker_id)
        return DispatchRecord(task.id, job.id, worker_id, DispatchState.FAILED, error=result.error)

    def recover_expired(self, now: int) -> tuple[str, ...]:
        return self.broker.scheduler.recover_expired(now)
