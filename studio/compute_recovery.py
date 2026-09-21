"""Checkpoint-aware recovery planning for failed elastic workers."""
from __future__ import annotations

from .fabric_scheduler import FabricPlacement, FabricScheduler, FabricWorker
from .hardware_requirements import HardwareRequirements


class ComputeRecoveryPlanner:
    def __init__(self, workers: tuple[FabricWorker, ...]):
        self.workers = tuple(workers)

    def recover(
        self,
        requirements: HardwareRequirements,
        *,
        failed_worker_ids: set[str],
        now: int,
    ) -> FabricPlacement:
        if any(not worker_id.strip() for worker_id in failed_worker_ids):
            raise ValueError("failed worker IDs cannot be empty")
        candidates = tuple(
            worker
            for worker in self.workers
            if worker.hardware.worker_id not in failed_worker_ids
        )
        if not candidates:
            raise RuntimeError("no verified replacement workers remain")
        return FabricScheduler(candidates).plan(requirements, now=now)
