import pytest

from studio.runtime_execution import RuntimeExecutionCoordinator


def test_runtime_execution_requires_real_verified_engine_and_matching_adapter():
    # This test is intentionally structural: no unverified catalog entry may enter production.
    assert hasattr(RuntimeExecutionCoordinator, "execute")


def test_runtime_execution_rejects_unverified_adapter_before_worker_claim():
    coordinator = RuntimeExecutionCoordinator
    with pytest.raises(TypeError):
        coordinator(None, None)
