import pytest

from studio.hardware_requirements import HardwareRequirements, GpuPlacement


def test_single_gpu_requirement_is_explicit():
    requirement = HardwareRequirements(min_gpu_count=1, min_vram_per_gpu_bytes=80 * 1024**3)
    assert requirement.min_gpu_count == 1
    assert requirement.min_vram_per_gpu_bytes == 80 * 1024**3
    assert requirement.placement == GpuPlacement.ANY


def test_topology_sensitive_multi_gpu_requirement_is_not_implicitly_satisfied():
    requirement = HardwareRequirements(
        min_gpu_count=8,
        min_vram_per_gpu_bytes=80 * 1024**3,
        placement=GpuPlacement.SAME_NVLINK_DOMAIN,
        require_nccl=True,
    )
    assert requirement.min_gpu_count == 8
    assert requirement.placement is GpuPlacement.SAME_NVLINK_DOMAIN
    assert requirement.require_nccl is True


def test_multi_node_requirement_requires_explicit_distributed_support():
    requirement = HardwareRequirements(
        min_gpu_count=16,
        placement=GpuPlacement.MULTI_NODE,
        require_nccl=True,
        allow_multi_node=True,
    )
    assert requirement.allow_multi_node is True


def test_invalid_requirements_fail_closed():
    with pytest.raises(ValueError):
        HardwareRequirements(min_gpu_count=0)
    with pytest.raises(ValueError):
        HardwareRequirements(min_gpu_count=2, placement=GpuPlacement.MULTI_NODE, allow_multi_node=False)
    with pytest.raises(ValueError):
        HardwareRequirements(min_gpu_count=2, require_nccl=True, allow_multi_node=False, placement=GpuPlacement.MULTI_NODE)
