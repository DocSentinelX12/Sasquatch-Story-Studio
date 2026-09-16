from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.scheduler import JobRequirements


def test_job_requirements_can_carry_explicit_gpu_placement_contract():
    hardware = HardwareRequirements(
        min_gpu_count=8,
        min_vram_per_gpu_bytes=80 * 1024**3,
        placement=GpuPlacement.SAME_NVLINK_DOMAIN,
    )
    requirements = JobRequirements(slots=8, hardware=hardware)
    assert requirements.hardware == hardware
