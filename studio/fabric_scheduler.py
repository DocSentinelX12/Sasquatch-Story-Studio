"""Elastic multi-provider placement above the canonical GPU capability layer.

This module plans eligible capacity only. It never replaces the durable
DistributedGpuAllocator, which remains the final reservation and fencing
authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from .compute_provider import ProviderResource, ProviderResourceState
from .gpu_capabilities import derive_gpu_capabilities
from .gpu_infrastructure import GpuHostObservation
from .hardware_requirements import GpuPlacement, HardwareRequirements, compute_capability_at_least
from .worker_registry import WorkerState


@dataclass(frozen=True)
class FabricWorker:
    provider_id: str
    resource: ProviderResource
    hardware: GpuHostObservation
    worker_state: WorkerState
    reliability_score: float = 1.0
    startup_seconds: int = 0

    def __post_init__(self) -> None:
        if self.resource.worker_id not in (None, self.hardware.worker_id):
            raise ValueError("provider resource worker identity does not match hardware observation")
        if not 0 <= self.reliability_score <= 1:
            raise ValueError("reliability score must be between 0 and 1")
        if self.startup_seconds < 0:
            raise ValueError("startup time cannot be negative")


@dataclass(frozen=True)
class FabricPlacement:
    workers: tuple[FabricWorker, ...]
    gpus_by_worker: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def node_count(self) -> int:
        return len(self.workers)

    @property
    def world_size(self) -> int:
        return sum(len(gpus) for _, gpus in self.gpus_by_worker)


class FabricScheduler:
    """Deterministic hard-constraint scheduler for heterogeneous providers."""

    def __init__(self, workers: tuple[FabricWorker, ...]):
        self.workers = tuple(sorted(workers, key=lambda item: (item.provider_id, item.resource.resource_id)))

    def plan(self, requirements: HardwareRequirements, *, now: int) -> FabricPlacement:
        if now < 0:
            raise ValueError("now cannot be negative")

        eligible: list[tuple[FabricWorker, tuple[str, ...]]] = []
        for worker in self.workers:
            if worker.worker_state not in {WorkerState.VERIFIED_AVAILABLE, WorkerState.VERIFIED_LIMITED}:
                continue
            if worker.resource.state is not ProviderResourceState.AVAILABLE:
                continue
            if worker.resource.expires_at is not None and now > worker.resource.expires_at:
                continue
            if not worker.resource.worker_id:
                continue
            capabilities = derive_gpu_capabilities(worker.hardware, now=now)
            selected: list[str] = []
            for gpu in sorted(worker.hardware.gpus, key=lambda item: (item.index, item.uuid)):
                record = capabilities.get(gpu.uuid)
                if not record.production_eligible:
                    continue
                if gpu.memory_total_mib * 1024**2 < requirements.min_vram_per_gpu_bytes:
                    continue
                if requirements.min_compute_capability is not None and not compute_capability_at_least(
                    gpu.compute_capability, requirements.min_compute_capability
                ):
                    continue
                if requirements.required_gpu_models and gpu.name not in requirements.required_gpu_models:
                    continue
                if requirements.require_nccl and not any(
                    record.state(name) == "verified" for name in []
                ):
                    # NCCL is checked explicitly below from the canonical record.
                    if record.state.__self__ is None:
                        raise AssertionError("unreachable")
                selected.append(gpu.uuid)
            if requirements.require_nccl:
                selected = [
                    uuid for uuid in selected
                    if capabilities.get(uuid).state(__import__("studio.gpu_capabilities", fromlist=["GpuCapabilityName"]).GpuCapabilityName.NCCL).value == "verified"
                ]
            if selected:
                eligible.append((worker, tuple(selected)))

        if requirements.placement is not GpuPlacement.MULTI_NODE:
            for worker, gpus in eligible:
                if len(gpus) >= requirements.min_gpu_count:
                    chosen = gpus[: requirements.min_gpu_count]
                    if sum(
                        gpu.memory_total_mib * 1024**2
                        for gpu in worker.hardware.gpus
                        if gpu.uuid in chosen
                    ) >= requirements.min_total_vram_bytes:
                        return FabricPlacement((worker,), ((worker.hardware.worker_id, chosen),))
            raise RuntimeError("no eligible worker satisfies the GPU requirement")

        if len(eligible) < 2:
            raise RuntimeError("multi-node scheduling requires at least two eligible workers")

        groups = []
        for size in range(2, len(eligible) + 1):
            for group in combinations(eligible, size):
                provider_ids = {worker.provider_id for worker, _ in group}
                if requirements.require_nccl and len(provider_ids) > 1:
                    continue
                if sum(len(gpus) for _, gpus in group) < requirements.min_gpu_count:
                    continue
                selected: list[tuple[str, tuple[str, ...]]] = []
                remaining = requirements.min_gpu_count
                for worker, gpus in sorted(group, key=lambda item: (-item[0].reliability_score, item[0].startup_seconds, item[0].provider_id, item[0].resource.resource_id)):
                    take = min(len(gpus), remaining)
                    if take:
                        selected.append((worker.hardware.worker_id, gpus[:take]))
                        remaining -= take
                    if remaining == 0:
                        break
                if remaining:
                    continue
                total_vram = sum(
                    gpu.memory_total_mib * 1024**2
                    for worker, _ in group
                    for gpu in worker.hardware.gpus
                    if any(uuid == gpu.uuid for _, uuids in selected for uuid in uuids)
                )
                if total_vram < requirements.min_total_vram_bytes:
                    continue
                groups.append((group, tuple(sorted(selected)), total_vram))

        if not groups:
            if requirements.require_nccl and len({worker.provider_id for worker, _ in eligible}) > 1:
                raise RuntimeError("cross-provider distributed NCCL evidence is required before cross-provider allocation")
            raise RuntimeError("eligible providers cannot satisfy the distributed GPU requirement")

        group, selected, _ = max(
            groups,
            key=lambda item: (
                sum(worker.reliability_score for worker, _ in item[0]),
                -sum(worker.startup_seconds for worker, _ in item[0]),
                -len(item[0]),
            ),
        )
        return FabricPlacement(tuple(worker for worker, _ in group), selected)
