import pytest

from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.gpu_scheduler import select_gpus
from studio.hardware_requirements import GpuPlacement, HardwareRequirements


TOPOLOGY = """        GPU0 GPU1 GPU2
GPU0    X    NV2  SYS
GPU1   NV2    X   NV2
GPU2   SYS   NV2   X
"""


def host():
    return GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=tuple(
            GpuDeviceObservation(i, f"GPU-{i}", "NVIDIA Test GPU", 81920, 0, f"00000000:{17+i:02x}:00.0", "10.0")
            for i in range(3)
        ),
        topology_text=TOPOLOGY,
        dcgm_available=False,
        dcgm_version=None,
        health_json=None,
    )


def test_scheduler_selects_only_free_gpus_for_any_placement():
    selected = select_gpus(host(), HardwareRequirements(min_gpu_count=2), used_gpu_uuids={"GPU-0"})
    assert selected == ("GPU-1", "GPU-2")


def test_scheduler_requires_nvlink_connectivity_for_same_domain():
    selected = select_gpus(
        host(),
        HardwareRequirements(min_gpu_count=2, placement=GpuPlacement.SAME_NVLINK_DOMAIN),
    )
    assert selected == ("GPU-0", "GPU-1")


def test_scheduler_fails_closed_when_topology_cannot_satisfy_requirement():
    with pytest.raises(RuntimeError):
        select_gpus(
            host(),
            HardwareRequirements(min_gpu_count=3, placement=GpuPlacement.SAME_NVLINK_DOMAIN),
        )
