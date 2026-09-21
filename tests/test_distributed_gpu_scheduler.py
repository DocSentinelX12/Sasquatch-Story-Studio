from studio.distributed_gpu_scheduler import DistributedGpuScheduler, DistributedWorker
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation, GpuTelemetryEvidence, GpuTelemetryStatus, TelemetryValue
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.nccl_evidence import NCCLTestEvidence
from studio.network_evidence import NetworkFabricObservation


def worker(worker_id, gpu_id):
    telemetry = GpuTelemetryEvidence("fixture", 100, "test", {"temperature_c": TelemetryValue(GpuTelemetryStatus.OBSERVED, 60, "fixture", 100)})
    observation = GpuHostObservation(
        worker_id=worker_id,
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, gpu_id, "NVIDIA Test GPU", 81920, 0, "00000000:17:00.0", "10.0", telemetry=telemetry),),
        topology_text="GPU0",
        dcgm_available=True,
        dcgm_version="observed",
        health_json="Overall Health: Healthy",
        nccl_evidence=NCCLTestEvidence("all_reduce_perf", "a" * 64, ("all_reduce_perf", "-g", "1"), 0, "b" * 64, (gpu_id,), "c" * 64),
    )
    network = NetworkFabricObservation(interface="ib0", transport="infiniband", link_speed_gbps=400, rdma=True, gpu_direct_rdma=True)
    return DistributedWorker(worker_id, observation, network)


def test_distributed_scheduler_allocates_across_workers_only_with_explicit_multi_node_evidence():
    scheduler = DistributedGpuScheduler((worker("worker-a", "GPU-A"), worker("worker-b", "GPU-B")))
    allocation = scheduler.allocate(
        HardwareRequirements(min_gpu_count=2, placement=GpuPlacement.MULTI_NODE, require_nccl=True, allow_multi_node=True, require_gpu_direct_network=True)
    )
    assert allocation.world_size == 2
    assert allocation.gpus_by_worker == (("worker-a", ("GPU-A",)), ("worker-b", ("GPU-B",)))


def test_distributed_scheduler_applies_total_vram_after_cross_worker_selection():
    scheduler = DistributedGpuScheduler((worker("worker-a", "GPU-A"), worker("worker-b", "GPU-B")))
    allocation = scheduler.allocate(
        HardwareRequirements(
            min_gpu_count=2,
            min_total_vram_bytes=160 * 1024**3,
            placement=GpuPlacement.MULTI_NODE,
            allow_multi_node=True,
        )
    )
    assert allocation.world_size == 2
