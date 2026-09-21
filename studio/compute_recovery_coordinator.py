"""Allocator-integrated recovery coordination for elastic GPU workloads.

This component fences the failed allocation first, then asks the same fabric
scheduler for a fresh placement and commits that exact placement through the
durable distributed allocator. Checkpoint transfer and workload restart remain
the execution layer's responsibility.
"""
from __future__ import annotations

from .distributed_gpu import DistributedGpuAllocation, DistributedGpuAllocator
from .fabric_scheduler import FabricScheduler, FabricWorker
from .hardware_requirements import HardwareRequirements


class ComputeRecoveryCoordinator:
    def __init__(self, allocator: DistributedGpuAllocator, workers: tuple[FabricWorker, ...]):
        self.allocator = allocator
        self.workers = tuple(workers)

    def recover(
        self,
        allocation_id: str,
        fencing_epoch: int,
        requirements: HardwareRequirements,
        *,
        failed_worker_ids: set[str],
        now: int,
        lease_seconds: int,
    ) -> DistributedGpuAllocation:
        if now < 0 or lease_seconds < 1:
            raise ValueError("recovery timing values are invalid")
        if not failed_worker_ids:
            raise ValueError("at least one failed worker is required")

        allocation = self.allocator.get(allocation_id)
        if allocation.fencing_epoch != fencing_epoch:
            raise PermissionError("fencing epoch does not match failed allocation")
        if allocation.state.value != "reserved":
            raise RuntimeError("only a reserved allocation can be recovered")

        self.allocator.fail(allocation_id, fencing_epoch, now)

        candidates = tuple(
            worker
            for worker in self.workers
            if worker.hardware.worker_id not in failed_worker_ids
           
        )
        if len(candidates) < 2:
            raise RuntimeError("no replacement worker group is available")

        placement = FabricScheduler(candidates).plan(requirements, now=now)
        return self.allocator.reserve_placement(
            allocation.task_id,
            requirements,
            placement,
            now=now,
            lease_seconds=lease_seconds,
        )
