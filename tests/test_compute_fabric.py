from __future__ import annotations

import pytest

from studio.compute_fabric import ComputeFabricAdmission
from studio.compute_provider import ProviderResource, ProviderResourceState, ResourceCostClass
from studio.compute_resources import ComputeResourceInventory
from studio.gpu_capabilities import derive_gpu_capabilities
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.resources import ComputeResource
from studio.worker_registry import WorkerRecord, WorkerState


def observation(worker_id: str = "worker-a") -> GpuHostObservation:
    return GpuHostObservation(
        worker_id=worker_id,
        driver_version="580.0",
        cuda_supported_version="13.0",
        gpus=(
            GpuDeviceObservation(
                0,
                f"{worker_id}-GPU-0",
                "NVIDIA Test GPU",
                81920,
                0,
                "0000:01:00.0",
                "10.0",
            ),
        ),
        topology_text=None,
        dcgm_available=True,
        dcgm_version="4.0",
        health_json="Overall Health: Healthy",
    )


def worker_record(obs: GpuHostObservation) -> WorkerRecord:
    resource = ComputeResource(
        id="resource-a",
        cpu_cores=32,
        memory_bytes=128 * 1024**3,
        gpu_count=1,
        gpu_models=(obs.gpus[0].name,),
        vram_bytes=obs.gpus[0].memory_total_mib * 1024 * 1024,
        logical_slots=1,
        scratch_bytes=100 * 1024**3,
    )
    capabilities = derive_gpu_capabilities(obs, now=100)
    return WorkerRecord(
        id=obs.worker_id,
        resource=resource,
        state=WorkerState.VERIFIED_AVAILABLE,
        observed_at=100,
        observation_source="authenticated_gpu_worker_agent",
        hardware_observation=obs,
        gpu_capability_digest=capabilities.digest(),
    )


def provisioned_resource(worker_id: str = "worker-a") -> ProviderResource:
    return ProviderResource(
        provider_id="provider-a",
        resource_id="resource-a",
        region="test",
        cost_class=ResourceCostClass.FREE,
        state=ProviderResourceState.PROVISIONED,
        worker_id=worker_id,
    )


def test_admission_binds_provider_resource_to_canonical_worker_capability() -> None:
    obs = observation()
    worker = worker_record(obs)
    inventory = ComputeResourceInventory()
    admitted = ComputeFabricAdmission(inventory).admit(
        provisioned_resource(),
        worker,
        now=100,
    )

    assert admitted.state is ProviderResourceState.AVAILABLE
    assert admitted.worker_id == worker.id
    assert admitted.capability_digest == worker.gpu_capability_digest
    assert inventory.get("provider-a", "resource-a") == admitted


def test_admission_populates_fabric_topology_when_explicit_topology_exists() -> None:
    from studio.gpu_topology import GpuTopologyEvidence

    obs = GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.0",
        cuda_supported_version="13.0",
        gpus=(obs_gpu := observation().gpus),
        topology_text="observed",
        dcgm_available=True,
        dcgm_version="4.0",
        health_json="Overall Health: Healthy",
        topology_evidence=GpuTopologyEvidence(
            gpu_uuids=(obs_gpu[0].uuid,),
            gpu_matrix=(("X",),),
            cpu_affinity=((obs_gpu[0].uuid, "0-31"),),
            nic_paths=((obs_gpu[0].uuid, "NIC0", "PIX"),),
            raw_text_sha256="a" * 64,
        ),
    )
    worker = worker_record(obs)
    from studio.fabric_topology import FabricTopologyRegistry
    topology = FabricTopologyRegistry()
    admitted = ComputeFabricAdmission(ComputeResourceInventory(), topology).admit(
        provisioned_resource(),
        worker,
        now=100,
    )

    assert topology.get("worker-a").resource == admitted
    assert topology.get("worker-a").topology_digest


def test_admission_rejects_capability_digest_mismatch() -> None:
    obs = observation()
    worker = worker_record(obs)
    worker = WorkerRecord(
        id=worker.id,
        resource=worker.resource,
        state=worker.state,
        observed_at=worker.observed_at,
        observation_source=worker.observation_source,
        hardware_observation=worker.hardware_observation,
        gpu_capability_digest="b" * 64,
    )

    with pytest.raises(ValueError, match="capability digest"):
        ComputeFabricAdmission(ComputeResourceInventory()).admit(
            provisioned_resource(),
            worker,
            now=100,
        )


def test_admission_rejects_unprovisioned_provider_resource() -> None:
    obs = observation()
    worker = worker_record(obs)
    resource = provisioned_resource().transition(ProviderResourceState.VERIFIED, now=100)

    with pytest.raises(ValueError, match="provisioned"):
        ComputeFabricAdmission(ComputeResourceInventory()).admit(resource, worker, now=100)


def test_fabric_scheduler_placement_is_reserved_exactly_without_replanning() -> None:
    from studio.distributed_gpu import DistributedGpuAllocator
    from studio.fabric_scheduler import FabricPlacement, FabricWorker
    from studio.hardware_requirements import GpuPlacement, HardwareRequirements

    observations = (observation("worker-a"), observation("worker-b"))
    records = tuple(worker_record(item) for item in observations)
    provider_resources = tuple(
        ProviderResource(
            provider_id="provider-a",
            resource_id=f"provider-resource-{item.id}",
            region="test",
            cost_class=ResourceCostClass.FREE,
            state=ProviderResourceState.AVAILABLE,
            worker_id=item.id,
        )
        for item in records
    )
    placement_workers = tuple(
        FabricWorker(
            provider_id=resource.provider_id,
            resource=resource,
            hardware=record.hardware_observation,
            worker_state=record.state,
        )
        for resource, record in zip(provider_resources, records)
    )
    placement = FabricPlacement(
        workers=placement_workers,
        gpus_by_worker=tuple(
            (record.id, (record.hardware_observation.gpus[0].uuid,))
            for record in records
        ),
    )
    registry = __import__("studio.worker_registry", fromlist=["WorkerRegistry"]).WorkerRegistry(records)
    allocator = DistributedGpuAllocator(registry)
    requirements = HardwareRequirements(
        min_gpu_count=2,
        placement=GpuPlacement.MULTI_NODE,
        allow_multi_node=True,
    )

    allocation = allocator.reserve_placement(
        "task-placement",
        requirements,
        placement,
        now=100,
        lease_seconds=60,
    )

    assert allocation.worker_ids == ("worker-a", "worker-b")
    assert allocation.gpus_by_worker == placement.gpus_by_worker
