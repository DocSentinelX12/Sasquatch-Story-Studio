"""Physical-GPU allocation layered onto the existing lease scheduler."""
from __future__ import annotations

from .gpu_scheduler import select_gpus
from .scheduler import Job, Scheduler
from .worker_registry import WorkerRegistry


class GpuAwareScheduler:
    """Preserve the existing job lease authority while reserving GPU UUIDs."""

    def __init__(self, scheduler: Scheduler, workers: WorkerRegistry):
        self.scheduler = scheduler
        self.workers = workers
        self._allocations: dict[str, tuple[str, ...]] = {}

    def choose_on_worker(self, worker_id: str, *, now: int, lease_seconds: int = 900) -> Job | None:
        worker = self.workers.get(worker_id)
        candidates = tuple(job for job in self.scheduler.snapshot() if job.state.value == "queued")
        for job in candidates:
            hardware = job.requirements.hardware
            if hardware is None:
                leased = self.scheduler.choose_on_worker(worker_id, worker.resource, 0, now, lease_seconds)
                if leased is not None:
                    self._allocations[leased.id] = ()
                return leased
            if worker.hardware_observation is None:
                continue
            used = {
                gpu_uuid
                for job_id, gpu_uuids in self._allocations.items()
                if self._job_is_leased(job_id)
                for gpu_uuid in gpu_uuids
            }
            try:
                selected = select_gpus(worker.hardware_observation, hardware, used_gpu_uuids=used)
            except RuntimeError:
                continue
            leased = self.scheduler.choose_on_worker(worker_id, worker.resource, 0, now, lease_seconds)
            if leased is not None:
                self._allocations[leased.id] = selected
                return leased
        return None

    def _job_is_leased(self, job_id: str) -> bool:
        return any(job.id == job_id and job.state.value == "leased" for job in self.scheduler.snapshot())

    def allocated_gpus(self, job_id: str) -> tuple[str, ...]:
        return self._allocations.get(job_id, ())

    def complete(self, job_id: str, worker_id: str) -> None:
        self.scheduler.complete(job_id, worker_id)
        self._allocations.pop(job_id, None)

    def requeue(self, job_id: str, worker_id: str) -> None:
        self.scheduler.requeue(job_id, worker_id)
        self._allocations.pop(job_id, None)

    def fail(self, job_id: str, worker_id: str) -> None:
        self.scheduler.fail(job_id, worker_id)
        self._allocations.pop(job_id, None)

    def recover_expired(self, now: int) -> tuple[str, ...]:
        recovered = self.scheduler.recover_expired(now)
        for job_id in recovered:
            self._allocations.pop(job_id, None)
        return recovered
