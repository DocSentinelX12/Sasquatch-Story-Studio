"""Fail-closed multi-node GPU placement with explicit fabric evidence."""
from __future__ import annotations

from dataclasses import dataclass, replace

from .gpu_infrastructure import GpuHostObservation
from .gpu_scheduler import select_gpus
from .hardware_requirements import GpuPlacement, HardwareRequirements
from .network_evidence import NetworkFabricObservation


@dataclass(frozen=True)
class DistributedWorker:
    worker_id: str
    hardware: GpuHostObservation
    network: NetworkFabricObservation


@dataclass(frozen=True)
class DistributedAllocation:
    world_size: int
    gpus_by_worker: tuple[tuple[str, tuple[str, ...]], ...]


class DistributedGpuScheduler:
    def __init__(self, workers: tuple[DistributedWorker, ...]):
        self.workers = tuple(sorted(workers, key=lambda worker: worker.worker_id))

    def allocate(self, requirements: HardwareRequirements) -> DistributedAllocation:
        if requirements.placement is not GpuPlacement.MULTI_NODE:
            raise ValueError("distributed scheduler requires MULTI_NODE placement")
        if len(self.workers) < 2:
            raise RuntimeError("multi-node allocation requires at least two observed workers")
        if requirements.require_gpu_direct_network and any(not worker.network.gpu_direct_rdma for worker in self.workers):
            raise RuntimeError("every participating worker must expose GPU-direct RDMA evidence")
        if any(not worker.network.rdma for worker in self.workers):
            raise RuntimeError("every participating worker must expose RDMA evidence")

        local_requirement = replace(requirements, placement=GpuPlacement.ANY, allow_multi_node=False, min_gpu_count=1)
        allocation: dict[str, list[str]] = {}
        used: dict[str, set[str]] = {}

        for worker in self.workers:
            if sum(len(gpus) for gpus in allocation.values()) >= requirements.min_gpu_count:
                break
            if requirements.require_nccl and worker.hardware.nccl_evidence is None:
                continue
            try:
                selected = select_gpus(worker.hardware, local_requirement, used_gpu_uuids=set())
            except RuntimeError:
                continue
            allocation[worker.worker_id] = list(selected)
            used[worker.worker_id] = set(selected)

        while sum(len(gpus) for gpus in allocation.values()) < requirements.min_gpu_count:
            progressed = False
            for worker in self.workers:
                current = allocation.get(worker.worker_id, [])
                if not current:
                    continue
                try:
                    selected = select_gpus(worker.hardware, local_requirement, used_gpu_uuids=set(current))
                except RuntimeError:
                    continue
                current.extend(selected)
                used[worker.worker_id].update(selected)
                progressed = True
                if sum(len(gpus) for gpus in allocation.values()) >= requirements.min_gpu_count:
                    break
            if not progressed:
                break

        total = sum(len(gpus) for gpus in allocation.values())
        if total < requirements.min_gpu_count or len(allocation) < 2:
            raise RuntimeError("observed cluster cannot satisfy the distributed GPU requirement")
        if requirements.min_total_vram_bytes:
            observed_vram = sum(
                gpu.memory_total_mib * 1024**2
                for worker in self.workers
                for gpu in worker.hardware.gpus
                if gpu.uuid in allocation.get(worker.worker_id, [])
            )
            if observed_vram < requirements.min_total_vram_bytes:
                raise RuntimeError("selected distributed GPUs do not satisfy total VRAM requirement")

        return DistributedAllocation(
            world_size=len(allocation),
            gpus_by_worker=tuple((worker_id, tuple(allocation[worker_id])) for worker_id in sorted(allocation)),
        )
