from studio.compute_recovery import ComputeRecoveryPlanner
from studio.fabric_scheduler import FabricWorker
from studio.compute_provider import ProviderResource, ProviderResourceState, ResourceCostClass
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.worker_registry import WorkerState


def w(worker_id):
    return FabricWorker(
        provider_id="provider",
        resource=ProviderResource("provider", worker_id, "test", ResourceCostClass.FREE, ProviderResourceState.AVAILABLE, worker_id=worker_id),
        hardware=GpuHostObservation(worker_id, "550", "12.4", (GpuDeviceObservation(0, worker_id, "A100", 80_000, 0, "pci", "8.0"),), "", True, "3", "Overall Health: Healthy"),
        worker_state=WorkerState.VERIFIED_AVAILABLE,
    )


def test_recovery_never_reuses_failed_worker():
    planner = ComputeRecoveryPlanner((w("w1"), w("w2"), w("w3")))
    requirements = HardwareRequirements(min_gpu_count=2, placement=GpuPlacement.MULTI_NODE, allow_multi_node=True)

    placement = planner.recover(requirements, failed_worker_ids={"w1"}, now=10)

    assert "w1" not in {item.hardware.worker_id for item in placement.workers}
    assert placement.world_size == 2
