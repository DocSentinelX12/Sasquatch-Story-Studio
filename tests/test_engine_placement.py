import pytest

from studio.engine_placement import EnginePlacementRegistry, EnginePlacementContract
from studio.hardware_requirements import HardwareRequirements


def test_engine_placement_contract_requires_explicit_hardware_requirements():
    registry = EnginePlacementRegistry()
    registry.register(
        EnginePlacementContract(
            engine_id="example-engine",
            model_revision="observed-model-revision",
            hardware=HardwareRequirements(min_gpu_count=1, min_vram_per_gpu_bytes=80 * 1024**3),
        )
    )
    assert registry.get("example-engine").hardware.min_gpu_count == 1


def test_missing_engine_placement_contract_fails_closed():
    registry = EnginePlacementRegistry()
    with pytest.raises(KeyError):
        registry.get("unregistered-engine")
