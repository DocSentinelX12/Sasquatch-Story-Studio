"""Capability-based broker for truthful production task routing."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

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


class ComputeBroker:
    """Deterministic routing over observed workers and an explicit verified-engine set."""

    _ACTIVE = {WorkerState.VERIFIED_AVAILABLE, WorkerState.VERIFIED_LIMITED}

    def __init__(self, scheduler: Scheduler, registry: WorkerRegistry, verified_engines: Iterable[str] = ()):
        self.scheduler = scheduler
        self.registry = registry
        self.verified_engines = frozenset(verified_engines)

    @staticmethod
    def _fits(task: ProductionTask, worker: WorkerRecord, verified_engines: frozenset[str]) -> tuple[bool, str]:
        req = task.requirements
        resource = worker.resource
        if worker.state not in ComputeBroker._ACTIVE:
            return False, f"worker state is {worker.state.value}"
        if not resource.healthy:
            return False, "worker resource is unhealthy"
        if resource.logical_slots < req.slots:
            return False, "insufficient logical slots"
        if resource.memory_bytes < req.memory_bytes:
            return False, "insufficient memory"
        if resource.vram_bytes < req.vram_bytes:
            return False, "insufficient VRAM"
        if resource.scratch_bytes < req.scratch_bytes:
            return False, "insufficient scratch storage"
        if req.power_watts and (resource.power_budget_watts is None or resource.power_budget_watts < req.power_watts):
            return False, "insufficient observed worker power budget"
        if not set(req.capabilities).issubset(resource.capabilities):
            return False, "required capability not observed"
        if not set(req.engines).issubset(resource.installed_engines):
            return False, "required engine not observed on worker"
        if not set(req.engines).issubset(verified_engines):
            return False, "required engine is not runtime verified"
        return True, "eligible"

    def select_worker(self, task: ProductionTask) -> BrokerDecision:
        eligible: list[str] = []
        rejected: list[tuple[str, str]] = []
        for worker in self.registry.snapshot():
            ok, reason = self._fits(task, worker, self.verified_engines)
            if ok:
                eligible.append(worker.id)
            else:
                rejected.append((worker.id, reason))
        selected = min(eligible) if eligible else None
        return BrokerDecision(task.id, tuple(eligible), tuple(rejected), selected, "eligible worker selected" if selected else "no verified eligible worker")

    def submit(self, task: ProductionTask) -> Job:
        job = Job(task.id, task.requirements, task.priority)
        self.scheduler.submit(job)
        return job

    def lease(self, task: ProductionTask, now: int, lease_seconds: int = 900) -> tuple[BrokerDecision, Job | None]:
        decision = self.select_worker(task)
        if decision.selected_worker is None:
            return decision, None
        worker = self.registry.get(decision.selected_worker)
        power_budget = worker.resource.power_budget_watts or 0
        job = self.scheduler.choose_on_worker(worker.id, worker.resource, power_budget, now, lease_seconds)
        if job is None:
            return BrokerDecision(task.id, decision.eligible_workers, decision.rejected_workers, None, "eligible capacity is currently reserved"), None
        return decision, job

    def release_or_requeue(self, job_id: str, now: int) -> bool:
        return job_id in self.scheduler.recover_expired(now)
