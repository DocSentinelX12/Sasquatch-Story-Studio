"""Real NVIDIA CUDA runtime verification.

This module never treats driver metadata or CUDA availability as proof of
execution. The verification path performs a real CUDA tensor operation on every
visible GPU and records the result for the caller.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .gpu_infrastructure import probe_nvidia_host


def validate_cuda_runtime(
    *,
    cuda_available: bool,
    device_count: int,
    expected_device_count: int,
    tensor_result: float,
) -> bool:
    if not cuda_available:
        raise RuntimeError("CUDA runtime is not available")
    if device_count != expected_device_count:
        raise RuntimeError(
            f"CUDA device count mismatch: observed {device_count}, expected {expected_device_count}"
        )
    if tensor_result != 3.0:
        raise RuntimeError(f"CUDA tensor verification produced unexpected result: {tensor_result}")
    return True


def verify_cuda_runtime(*, output_path: str | Path) -> dict:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for real CUDA runtime verification") from exc

    observation = probe_nvidia_host("local-gpu-verifier")
    expected = observation.gpu_count
    results: list[float] = []
    for index in range(expected):
        torch.cuda.set_device(index)
        value = torch.tensor([1.0], device=f"cuda:{index}") * 3.0
        torch.cuda.synchronize(index)
        results.append(float(value.item()))

    validate_cuda_runtime(
        cuda_available=bool(torch.cuda.is_available()),
        device_count=int(torch.cuda.device_count()),
        expected_device_count=expected,
        tensor_result=results[0] if results else 0.0,
    )
    if any(result != 3.0 for result in results):
        raise RuntimeError(f"CUDA verification returned inconsistent per-GPU results: {results}")

    evidence = {
        "verification": "real_cuda_runtime",
        "recorded_at": int(time.time()),
        "torch_version": str(torch.__version__),
        "torch_cuda_version": str(torch.version.cuda),
        "device_count": expected,
        "gpu_uuids": [gpu.uuid for gpu in observation.gpus],
        "driver_version": observation.driver_version,
        "cuda_supported_version": observation.cuda_supported_version,
        "tensor_results": results,
        "hardware_observation": json.loads(observation.canonical_json()),
    }
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    verify_cuda_runtime(output_path=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
