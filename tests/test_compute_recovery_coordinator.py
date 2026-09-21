from __future__ import annotations

import pytest

from studio.compute_provider import ProviderResource, ProviderResourceState, ResourceCostClass
from studio.distributed_gpu import DistributedGpuAllocator
from studio.fabric_scheduler import FabricScheduler, FabricWorker
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.resources import ComputeResource
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


def _worker(worker_id: str) -> WorkerRecord:
    obs = GpuHostObservation(
        worker_id=worker_id,
        driver_version="580",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, f"{worker_id}-gpu", "NVIDIA Test", 81920, 0, "0000:01:00.0", "10.0"),),
        topology_text=None,
        dcgm_available=True,
        dcgm_version="4",
        health_json="Overall Health: Healthy",
    )
    return WorkerRecord(
        id=worker_id,
        resource=ComputeResource(f"{worker_id}-resource", 32, 128 * 1024**3, gpu_count=1, gpu_models=("NVIDIA Test",), vram_bytes=81920 * 1024**2),
        state=WorkerState.VERIFIED_AVAILABLE,
        observed_at=100,
        observation_source="authenticated_gpu_worker_agent",
        hardware_observation=obs,
        gpu_capability_digest=__import__("studio.gpu_capabilities", fromlist=["derive_gpu_capabilities"]).derive_gpu_capabilities(obs, now=100).digest(),
    )


def _fabric_worker(record: WorkerRecord) -> FabricWorker:
    resource = ProviderResource(
        provider_id="provider-a",
        resource_id=f"{record.id}-provider-resource",
        region="test",
        cost_class=ResourceCostClass.FREE,
        state=ProviderResourceState.AVAILABLE,
        worker_id=record.id,
    )
    return FabricWorker("provider-a", resource, record.hardware_observation, record.state)


def test_recovery_coordinator_fences_failed_allocation_and_reserves_replacement() -> None:
    from studio.compute_recovery_coordinator import ComputeRecoveryCoordinator

    records = (_worker("worker-a"), _worker("worker-b"), _worker("worker-c"))
    registry = WorkerRegistry(records)
    allocator = DistributedGpuAllocator(registry)
    requirements = HardwareRequirements(min_gpu_count=2, placement=GpuPlacement.MULTI_NODE, allow_multi_node=True)
    workers = tuple(_fabric_worker(record) for record in records)
    placement = FabricScheduler(workers).plan(requirements, now=100)
    allocation = allocator.reserve_placement("task", requirements, placement, now=100, lease_seconds=60)

    coordinator = ComputeRecoveryCoordinator(allocator, workers)
    recovered = coordinator.recover(
        allocation.allocation_id,
        allocation.fencing_epoch,
        requirements,
        failed_worker_ids={"worker-a"},
        now=110,
        lease_seconds=60,
    )

    assert allocation.allocation_id != recovered.allocation_id
    assert allocator.get(allocation.allocation_id).state.value == "failed"
    assert "worker-a" not in recovered.worker_ids


def test_recovery_rejects_when_no_replacement_group_exists() -> None:
    from studio.compute_recovery_coordinator import ComputeRecoveryCoordinator

    records = (_worker("worker-a"), _worker("worker-b"))
    registry = WorkerRegistry(records)
    allocator = DistributedGpuAllocator(registry)
    requirements = HardwareRequirements(min_gpu_count=2, placement=GpuPlacement.MULTI_NODE, allow_multi_node=True)
    workers = tuple(_fabric_worker(record) for record in records)
    placement = FabricScheduler(workers).plan(requirements, now=100)
    allocation = allocator.reserve_placement("task", requirements, placement, now=100, lease_seconds=60)

    coordinator = ComputeRecoveryCoordinator(allocator, workers)
    with pytest.raises(RuntimeError, match="replacement"):
        coordinator.recover(
            allocation.allocation_id,
            allocation.fencing_epoch,
            requirements,
            failed_worker_ids={"worker-a"},
            now=110,
            lease_seconds=60,
        )
