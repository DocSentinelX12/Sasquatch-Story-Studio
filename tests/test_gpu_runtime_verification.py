from __future__ import annotations

import pytest

from studio.gpu_runtime_verification import validate_cuda_runtime
from studio.gpu_direct_verification import validate_gpu_direct_output
from studio.nccl_runtime_verification import validate_nccl_result


def test_cuda_runtime_verification_requires_real_cuda_and_expected_device_count():
    assert validate_cuda_runtime(
        cuda_available=True,
        device_count=2,
        expected_device_count=2,
        tensor_result=3.0,
    ) is True

    with pytest.raises(RuntimeError, match="CUDA"):
        validate_cuda_runtime(
            cuda_available=False,
            device_count=2,
            expected_device_count=2,
            tensor_result=3.0,
        )


def test_cuda_runtime_verification_rejects_device_count_mismatch():
    with pytest.raises(RuntimeError, match="device count"):
        validate_cuda_runtime(
            cuda_available=True,
            device_count=1,
            expected_device_count=2,
            tensor_result=3.0,
        )


def test_nccl_result_requires_successful_collective_and_expected_sum():
    assert validate_nccl_result(exit_code=0, observed_sum=8.0, expected_sum=8.0) is True

    with pytest.raises(RuntimeError, match="NCCL"):
        validate_nccl_result(exit_code=1, observed_sum=8.0, expected_sum=8.0)

    with pytest.raises(RuntimeError, match="result"):
        validate_nccl_result(exit_code=0, observed_sum=7.0, expected_sum=8.0)


def test_gpu_direct_verification_requires_explicit_success_marker():
    assert validate_gpu_direct_output("GPU_DIRECT_VERIFIED\nlatency=1.2", "GPU_DIRECT_VERIFIED") is True

    with pytest.raises(RuntimeError, match="marker"):
        validate_gpu_direct_output("command completed successfully", "GPU_DIRECT_VERIFIED")

    with pytest.raises(RuntimeError, match="marker"):
        validate_gpu_direct_output("", "GPU_DIRECT_VERIFIED")
