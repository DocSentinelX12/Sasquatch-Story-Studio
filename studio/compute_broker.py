"""Capability-based broker for truthful production task routing."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from .distributed_gpu import DistributedGpuAllocation, DistributedGpuAllocator
from .gpu_placement import evaluate_gpu_placement
from .scheduler import Job, JobRequirements, Scheduler
from .worker_registry import WorkerRecord, WorkerRegistry, WorkerState


@dataclass(frozen=True)
class ProductionTask:
    id: str
    requirements: JobRequirements
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("task id is required")


@dataclass(frozen=True)
class BrokerDecision:
    task_id: str
    eligible_workers: tuple[str, ...]
    rejected_workers: tuple[tuple[str, str], ...]
    selected_worker: str | None
    reason: str
    selected_gpu_uuids: tuple[str, ...] = ()


class ComputeBroker:
    """Deterministic routing over observed workers and an explicit verified-engine set."""

    _ACTIVE = {WorkerState.VERIFIED_AVAILABLE, WorkerState.VERIFIED_LIMITED}

    def __init__(
        self,
        scheduler: Scheduler,
        registry: WorkerRegistry,
        verified_engines: Iterable[str] = (),
        distributed_allocator: DistributedGpuAllocator | None = None,
    ):
        self.scheduler = scheduler
        self.registry = registry
        self.verified_engines = frozenset(verified_engines)
        self.distributed_allocator = distributed_allocator

    @staticmethod
    def _fits(task: ProductionTask, worker: WorkerRecord, verified_engines: frozenset[str]) -> tuple[bool, str, tuple[str, ...]]:
        req = task.requirements
        resource = worker.resource
        if worker.state not in ComputeBroker._ACTIVE:
            return False, f"worker state is {worker.state.value}", ()
        if not resource.healthy:
            return False, "worker resource is unhealthy", ()
        if resource.logical_slots < req.slots:
            return False, "insufficient logical slots", ()
        if resource.memory_bytes < req.memory_bytes:
            return False, "insufficient memory", ()
        if resource.vram_bytes < req.vram_bytes:
            return False, "insufficient VRAM", ()
        if resource.scratch_bytes < req.scratch_bytes:
            return False, "insufficient scratch storage", ()
        if req.power_watts and (resource.power_budget_watts is None or resource.power_budget_watts < req.power_watts):
            return False, "insufficient observed worker power budget", ()
        if not set(req.capabilities).issubset(resource.capabilities):
            return False, "required capability not observed", ()
        if not set(req.engines).issubset(resource.installed_engines):
            return False, "required engine not observed on worker", ()
        if not set(req.engines).issubset(verified_engines):
            return False, "required engine is not runtime verified", ()
        if req.hardware is not None:
            placement = evaluate_gpu_placement(req.hardware, worker.hardware_observation)
            if not placement.eligible:
                return False, placement.reason, ()
            return True, "eligible", placement.gpu_uuids
        return True, "eligible", ()

    def select_worker(self, task: ProductionTask) -> BrokerDecision:
        eligible: list[str] = []
        rejected: list[tuple[str, str]] = []
        placements: dict[str, tuple[str, ...]] = {}
        for worker in self.registry.snapshot():
            ok, reason, gpu_uuids = self._fits(task, worker, self.verified_engines)
            if ok:
                eligible.append(worker.id)
                placements[worker.id] = gpu_uuids
            else:
                rejected.append((worker.id, reason))
        ordered = sorted(
            eligible,
            key=lambda worker_id: self._placement_key(
                task,
                self.registry.get(worker_id),
                placements[worker_id],
            ),
        )
        selected = ordered[0] if ordered else None
        return BrokerDecision(
            task.id,
            tuple(eligible),
            tuple(rejected),
            selected,
            "eligible worker selected" if selected else "no verified eligible worker",
            placements.get(selected, ()) if selected else (),
        )

    @staticmethod
    def _placement_key(
        task: ProductionTask,
        worker: WorkerRecord,
        gpu_uuids: tuple[str, ...],
    ) -> tuple[int, int, int, int, int, str]:
        """Prefer the smallest verified worker that can satisfy the task.

        Best-fit placement preserves larger workers for workloads that actually
        need them. The worker ID remains the final deterministic tie-breaker.
        """
        req = task.requirements
        resource = worker.resource

        def normalized_excess(capacity: int, required: int) -> int:
            if required <= 0:
                return 0
            return max(capacity - required, 0) * 1_000_000 // required

        hardware_gpu_count = req.hardware.min_gpu_count if req.hardware is not None else 0
        return (
            normalized_excess(resource.logical_slots, req.slots),
            normalized_excess(resource.memory_bytes, req.memory_bytes),
            normalized_excess(resource.vram_bytes, req.vram_bytes),
            normalized_excess(resource.scratch_bytes, req.scratch_bytes),
            normalized_excess(resource.power_budget_watts or 0, req.power_watts),
            max(resource.gpu_count - hardware_gpu_count, 0),
            worker.id,
        )

    def reserve_distributed(
        self,
        task: ProductionTask,
        now: int,
        lease_seconds: int = 900,
        *,
        distributed_nccl=None,
        gpu_direct_network=None,
    ) -> DistributedGpuAllocation:
        """Reserve an exact multi-worker GPU allocation for a distributed task.

        Distributed work is deliberately kept out of the single-worker
        scheduler. The authoritative distributed allocator owns the gang
        reservation, exact GPU identities, fencing, and expiry.
        """
        requirements = task.requirements.hardware
        if requirements is None or requirements.placement.value != "multi_node":
            raise ValueError("distributed broker routing requires MULTI_NODE hardware requirements")
        if self.distributed_allocator is None:
            raise RuntimeError("distributed GPU allocator is not configured")
        return self.distributed_allocator.reserve(
            task.id,
            requirements,
            now,
            lease_seconds,
            distributed_nccl=distributed_nccl,
            gpu_direct_network=gpu_direct_network,
        )

    def submit(self, task: ProductionTask) -> Job:
        job = Job(task.id, task.requirements, task.priority)
        self.scheduler.submit(job)
        return job

    def lease(self, task: ProductionTask, now: int, lease_seconds: int = 900) -> tuple[BrokerDecision, Job | None]:
        decision = self.select_worker(task)
        if decision.selected_worker is None:
            return decision, None
        ordered_workers = sorted(
            decision.eligible_workers,
            key=lambda worker_id: self._placement_key(
                task,
                self.registry.get(worker_id),
                next(
                    (
                        gpu_uuids
                        for candidate_id, gpu_uuids in ((
                            worker_id,
                            decision.selected_gpu_uuids,
                        ),)
                        if candidate_id == worker_id
                    ),
                    (),
                ),
            ),
        )
        # Re-evaluate placement for every eligible worker so fallback uses the
        # exact GPU identities that were admitted for that worker.
        placements = {}
        for worker_id in decision.eligible_workers:
            ok, reason, gpu_uuids = self._fits(task, self.registry.get(worker_id), self.verified_engines)
            if ok:
                placements[worker_id] = gpu_uuids

        for worker_id in sorted(
            placements,
            key=lambda candidate_id: self._placement_key(
                task,
                self.registry.get(candidate_id),
                placements[candidate_id],
            ),
        ):
            worker = self.registry.get(worker_id)
            job = self.scheduler.choose_on_worker(
                worker.id,
                worker.resource,
                worker.resource.power_budget_watts or 0,
                now,
                lease_seconds,
                job_id=task.id,
                gpu_uuids=placements[worker_id],
            )
            if job is not None:
                return BrokerDecision(
                    task.id,
                    decision.eligible_workers,
                    decision.rejected_workers,
                    worker.id,
                    "eligible worker selected",
                    placements[worker.id],
                ), job
        return BrokerDecision(
            task.id,
            decision.eligible_workers,
            decision.rejected_workers,
            None,
            "eligible workers are not currently leaseable",
            (),
        ), None

    def release_or_requeue(self, job_id: str, now: int) -> bool:
        return job_id in self.scheduler.recover_expired(now)
