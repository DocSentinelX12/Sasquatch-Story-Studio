from studio.compute_provider import ComputeProvider, ProviderResource, ProviderResourceState, ResourceCostClass
from studio.fabric_scheduler import FabricScheduler, FabricWorker
from studio.gpu_capabilities import derive_gpu_capabilities
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.worker_registry import WorkerState
from studio.resources import ComputeResource


def obs(worker_id, uuid, model="NVIDIA A100"):
    return GpuHostObservation(
        worker_id=worker_id,
        driver_version="550.1",
        cuda_supported_version="12.4",
        gpus=(GpuDeviceObservation(0, uuid, model, 80_000, 0, "0000:00:00.0", "8.0"),),
        topology_text="",
        dcgm_available=True,
        dcgm_version="3",
        health_json="Overall Health: Healthy",
    )


def worker(provider_id, worker_id, uuid):
    resource = ProviderResource(
        provider_id=provider_id,
        resource_id=worker_id,
        region="test",
        cost_class=ResourceCostClass.FREE,
        state=ProviderResourceState.AVAILABLE,
        worker_id=worker_id,
    )
    return FabricWorker(
        provider_id=provider_id,
        resource=resource,
        hardware=obs(worker_id, uuid),
        worker_state=WorkerState.VERIFIED_AVAILABLE,
    )


def test_scheduler_can_combine_multiple_providers_for_non_distributed_work():
    workers = tuple(worker("a", f"a-{i}", f"GPU-A-{i}") for i in range(6)) + tuple(
        worker("b", f"b-{i}", f"GPU-B-{i}") for i in range(6)
    )
    placement = FabricScheduler(workers).plan(
        HardwareRequirements(min_gpu_count=12, placement=GpuPlacement.MULTI_NODE, allow_multi_node=True),
        now=10,
    )
    assert placement.node_count == 12
    assert {item.provider_id for item in placement.workers} == {"a", "b"}


def test_scheduler_rejects_cross_provider_nccl_without_distributed_fabric_evidence():
    workers = (worker("a", "a-1", "GPU-A"), worker("b", "b-1", "GPU-B"))
    requirements = HardwareRequirements(
        min_gpu_count=2,
        placement=GpuPlacement.MULTI_NODE,
        allow_multi_node=True,
        require_nccl=True,
    )
    try:
        FabricScheduler(workers).plan(requirements, now=10)
    except RuntimeError as exc:
        assert "cross-provider" in str(exc)
    else:
        raise AssertionError("cross-provider NCCL allocation was not rejected")


def test_scheduler_has_no_twelve_node_ceiling():
    workers = tuple(worker("a", f"a-{i}", f"GPU-{i}") for i in range(20))
    requirements = HardwareRequirements(min_gpu_count=20, placement=GpuPlacement.MULTI_NODE, allow_multi_node=True)
    placement = FabricScheduler(workers).plan(requirements, now=10)
    assert placement.node_count == 20
