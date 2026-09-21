from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.gpu_topology import GpuTopologyEvidence
from studio.gpu_scheduler import select_gpus
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.nccl_evidence import NCCLTestEvidence


def test_scheduler_accepts_nccl_requirement_only_with_matching_successful_evidence():
    host = GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=(
            GpuDeviceObservation(0, "GPU-0", "NVIDIA Test GPU", 81920, 0, "00000000:17:00.0", "10.0"),
            GpuDeviceObservation(1, "GPU-1", "NVIDIA Test GPU", 81920, 0, "00000000:18:00.0", "10.0"),
        ),
        topology_text="GPU0 GPU1\nGPU0 X NV2\nGPU1 NV2 X",
        dcgm_available=True,
        dcgm_version="observed",
        health_json="Overall Health: Healthy",
        topology_evidence=GpuTopologyEvidence(\n            gpu_uuids=("GPU-0", "GPU-1"),\n            gpu_matrix=(("X", "NV2"), ("NV2", "X")),\n            cpu_affinity=(("GPU-0", "0-31"), ("GPU-1", "32-63")),\n            nic_paths=(),\n            raw_text_sha256="c" * 64,\n        ),\n        nccl_evidence=NCCLTestEvidence(
            executable="all_reduce_perf",
            executable_sha256="a" * 64,
            command=("all_reduce_perf", "-g", "2"),
            exit_code=0,
            output_sha256="b" * 64,
            gpu_uuids=("GPU-0", "GPU-1"),
            topology_digest="c" * 64,
        ),
    )
    selected = select_gpus(host, HardwareRequirements(min_gpu_count=2, placement=GpuPlacement.SAME_NVLINK_DOMAIN, require_nccl=True))
    assert selected == ("GPU-0", "GPU-1")
