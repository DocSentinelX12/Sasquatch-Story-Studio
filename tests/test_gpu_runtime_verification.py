from __future__ import annotations

import pytest

from studio.gpu_runtime_verification import CUDARuntimeEvidence, validate_cuda_runtime
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


def test_cuda_runtime_evidence_rejects_runtime_identity_mismatch():
    with pytest.raises(ValueError, match="UUIDs"):
        CUDARuntimeEvidence(
            recorded_at=1700000000,
            gpu_uuids=("GPU-0",),
            runtime_gpu_uuids=("GPU-1",),
            tensor_results=(3.0,),
            torch_version="2.8.0",
            torch_cuda_version="13.0",
            driver_version="580.95.05",
            cuda_supported_version="13.0",
        )


def test_cuda_runtime_evidence_requires_one_successful_result_per_gpu():
    evidence = CUDARuntimeEvidence(
        recorded_at=1700000000,
        gpu_uuids=("GPU-0", "GPU-1"),
        runtime_gpu_uuids=("GPU-0", "GPU-1"),
        tensor_results=(3.0, 3.0),
        torch_version="2.8.0",
        torch_cuda_version="13.0",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
    )
    assert evidence.gpu_uuids == evidence.runtime_gpu_uuids
