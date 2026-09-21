from __future__ import annotations

from studio.compute_provider import ComputeProvider, ProviderResource, ProviderResourceState, ResourceCostClass
from studio.compute_provisioning import ProvisioningManager
from studio.compute_resources import ComputeResourceInventory
from studio.compute_fabric import ComputeFabricAdmission
from studio.gpu_capabilities import derive_gpu_capabilities
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.resources import ComputeResource
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


def _worker() -> WorkerRecord:
    observation = GpuHostObservation(
        worker_id="worker-a",
        driver_version="580",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-A", "NVIDIA Test", 81920, 0, "0000:01:00.0", "10.0"),),
        topology_text=None,
        dcgm_available=True,
        dcgm_version="4",
        health_json="Overall Health: Healthy",
    )
    capability_digest = derive_gpu_capabilities(observation, now=100).digest()
    resource = ComputeResource("worker-resource", 32, 128 * 1024**3, gpu_count=1, gpu_models=("NVIDIA Test",), vram_bytes=81920 * 1024**2)
    return WorkerRecord(
        id="worker-a",
        resource=resource,
        state=WorkerState.VERIFIED_AVAILABLE,
        observed_at=100,
        observation_source="authenticated_gpu_worker_agent",
        hardware_observation=observation,
        gpu_capability_digest=capability_digest,
    )


class _Provisioner:
    def provision(self, resource: ProviderResource, *, now: int) -> ProviderResource:
        return resource.transition(ProviderResourceState.PROVISIONED, now=now)


def test_fabric_controller_connects_acquired_provider_resource_to_verified_worker() -> None:
    from studio.compute_fabric_controller import ComputeFabricController

    worker = _worker()
    resource = ProviderResource(
        provider_id="provider-a",
        resource_id="resource-a",
        region="free-region",
        cost_class=ResourceCostClass.FREE,
        state=ProviderResourceState.ACQUIRED,
        worker_id="worker-a",
    )
    controller = ComputeFabricController(
        provisioning=ProvisioningManager(_Provisioner()),
        workers=WorkerRegistry((worker,)),
        inventory=ComputeResourceInventory(),
    )

    snapshot = controller.reconcile((resource,), now=100)

    admitted = controller.inventory.get("provider-a", "resource-a")
    assert admitted.state is ProviderResourceState.AVAILABLE
    assert admitted.capability_digest == worker.gpu_capability_digest
    assert snapshot.available == 1
    assert snapshot.failed == ()


def test_fabric_controller_keeps_failed_resources_out_of_available_capacity() -> None:
    from studio.compute_fabric_controller import ComputeFabricController

    worker = _worker()
    resource = ProviderResource(
        provider_id="provider-a",
        resource_id="resource-a",
        region="free-region",
        cost_class=ResourceCostClass.FREE,
        state=ProviderResourceState.DISCOVERED,
        worker_id="worker-a",
    )
    controller = ComputeFabricController(
        provisioning=ProvisioningManager(_Provisioner()),
        workers=WorkerRegistry((worker,)),
        inventory=ComputeResourceInventory(),
    )

    snapshot = controller.reconcile((resource,), now=100)

    assert snapshot.available == 0
    assert snapshot.failed == (("provider-a", "resource-a", "resource is not acquired"),)
\n
def test_fabric_controller_can_close_the_loop_from_acquisition_to_verified_capacity() -> None:
    from studio.compute_capacity_controller import ComputeCapacityController
    from studio.compute_fabric_controller import ComputeFabricController

    class Adapter:
        def __init__(self, provider_id: str, count: int):
            self.provider = ComputeProvider(provider_id, provider_id)
            self.resources = tuple(
                ProviderResource(provider_id, f"{provider_id}-{i}", "free-region", ResourceCostClass.FREE)
                for i in range(count)
            )

        def discover(self):
            return self.resources

        def authorize(self, resource):
            return resource.transition(ProviderResourceState.AUTHORIZED)

        def acquire(self, resource, *, now):
            return resource.transition(ProviderResourceState.ACQUIRED, now=now)

        def release(self, resource):
            return resource.transition(ProviderResourceState.RELEASED)

    class BindingProvisioner:
        def provision(self, resource, *, now):
            worker_id = f"worker-{resource.provider_id}-{resource.resource_id.rsplit('-', 1)[-1]}"
            provisioned = resource.transition(ProviderResourceState.PROVISIONED, now=now)
            return provisioned.__class__(**{**provisioned.__dict__, "worker_id": worker_id})

    workers = []
    for provider_id, count in (("a", 7), ("b", 5)):
        for index in range(count):
            worker_id = f"worker-{provider_id}-{index}"
            observation = GpuHostObservation(
                worker_id=worker_id,
                driver_version="580",
                cuda_supported_version="13.0",
                gpus=(GpuDeviceObservation(0, f"GPU-{worker_id}", "NVIDIA Test", 81920, 0, "0000:01:00.0", "10.0"),),
                topology_text=None,
                dcgm_available=True,
                dcgm_version="4",
                health_json="Overall Health: Healthy",
            )
            resource = ComputeResource(
                f"resource-{worker_id}", 32, 128 * 1024**3, gpu_count=1,
                gpu_models=("NVIDIA Test",), vram_bytes=81920 * 1024**2,
            )
            workers.append(WorkerRecord(
                id=worker_id,
                resource=resource,
                state=WorkerState.VERIFIED_AVAILABLE,
                observed_at=100,
                observation_source="authenticated_gpu_worker_agent",
                hardware_observation=observation,
                gpu_capability_digest=derive_gpu_capabilities(observation, now=100).digest(),
            ))

    capacity = ComputeCapacityController((Adapter("a", 7), Adapter("b", 5)))
    controller = ComputeFabricController(
        provisioning=ProvisioningManager(BindingProvisioner()),
        workers=WorkerRegistry(tuple(workers)),
        inventory=ComputeResourceInventory(),
    )

    result = controller.ensure_capacity(capacity, now=100)

    assert result.target_nodes == 12
    assert result.acquired_nodes == 12
    assert result.verified_nodes == 12
    assert result.target_satisfied is True
    assert result.reconciliation.failed == ()
    assert {resource.provider_id for resource in controller.inventory.snapshot()} == {"a", "b"}

