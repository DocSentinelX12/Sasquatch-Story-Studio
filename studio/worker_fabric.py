"""Durable distributed worker execution and checkpoint-aware reassignment."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping, Protocol

from .compute_broker import ComputeBroker, ProductionTask
from .distributed_execution import DistributedLaunchSpec
from .distributed_gpu import DistributedGpuAllocation
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


@dataclass(frozen=True)
class DistributedDispatchRecord:
    task_id: str
    allocation_id: str | None
    state: DispatchState
    output_refs: tuple[str, ...] = ()
    worker_results: tuple[dict[str, object], ...] = ()
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
        distributed_coordinator=None,
    ):
        self.broker = broker
        self.executors = dict(executors)
        self.lease_provider = lease_provider
        self.distributed_coordinator = distributed_coordinator

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

    def dispatch_distributed(
        self,
        task: ProductionTask,
        launch_spec: DistributedLaunchSpec,
        now: int,
        lease_seconds: int = 900,
    ) -> DistributedDispatchRecord:
        """Reserve and execute a real multi-worker allocation as one gang.

        This path never invokes the single-worker scheduler. Allocation,
        per-worker authenticated leases, concurrent launch, and allocation
        lifecycle are owned by the distributed control plane.
        """
        hardware = task.requirements.hardware
        if hardware is None or hardware.placement.value != "multi_node":
            raise ValueError("distributed dispatch requires MULTI_NODE hardware requirements")
        if self.broker.distributed_allocator is None:
            raise RuntimeError("distributed GPU allocator is not configured")
        if self.distributed_coordinator is None:
            raise RuntimeError("distributed execution coordinator is not configured")

        allocation = self.broker.reserve_distributed(
            task,
            now=now,
            lease_seconds=lease_seconds,
        )
        try:
            results = self.distributed_coordinator.execute(allocation, launch_spec, now)
        except Exception as exc:
            try:
                self.broker.distributed_allocator.fail(
                    allocation.allocation_id,
                    allocation.fencing_epoch,
                    now,
                )
            except (RuntimeError, PermissionError, ValueError):
                pass
            return DistributedDispatchRecord(
                task.id,
                allocation.allocation_id,
                DispatchState.REQUEUED,
                error=str(exc),
            )

        if not results:
            return DistributedDispatchRecord(
                task.id,
                allocation.allocation_id,
                DispatchState.FAILED,
                error="distributed coordinator returned no worker results",
            )
        failed = tuple(result for result in results if result.get("state") != "completed")
        if failed:
            return DistributedDispatchRecord(
                task.id,
                allocation.allocation_id,
                DispatchState.REQUEUED,
                worker_results=results,
                error=str(failed[0].get("error") or "distributed worker execution failed"),
            )

        rank_zero = next((result for result in results if result.get("output_refs")), None)
        if rank_zero is None:
            return DistributedDispatchRecord(
                task.id,
                allocation.allocation_id,
                DispatchState.FAILED,
                worker_results=results,
                error="distributed execution completed without a rank-zero output artifact",
            )
        return DistributedDispatchRecord(
            task.id,
            allocation.allocation_id,
            DispatchState.COMPLETED,
            output_refs=tuple(str(ref) for ref in rank_zero["output_refs"]),
            worker_results=results,
        )

    def recover_expired(self, now: int) -> tuple[str, ...]:
        return self.broker.scheduler.recover_expired(now)
