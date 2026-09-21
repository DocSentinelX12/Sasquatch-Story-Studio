"""Real NVIDIA CUDA runtime verification.

This module never treats driver metadata or CUDA availability as proof of
execution. The verification path performs a real CUDA tensor operation on every
visible GPU and binds the runtime devices back to the physical GPU observation.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

from .gpu_infrastructure import probe_nvidia_host


@dataclass(frozen=True)
class CUDARuntimeEvidence:
    recorded_at: int
    gpu_uuids: tuple[str, ...]
    runtime_gpu_uuids: tuple[str, ...]
    tensor_results: tuple[float, ...]
    torch_version: str
    torch_cuda_version: str
    driver_version: str
    cuda_supported_version: str

    def __post_init__(self) -> None:
        if self.recorded_at < 0:
            raise ValueError("CUDA verification timestamp cannot be negative")
        if not self.gpu_uuids or self.gpu_uuids != self.runtime_gpu_uuids:
            raise ValueError("CUDA evidence must bind the runtime UUIDs to the observed GPU UUIDs")
        if len(self.tensor_results) != len(self.gpu_uuids) or any(value != 3.0 for value in self.tensor_results):
            raise ValueError("CUDA evidence must contain one successful tensor result per GPU")
        if not self.torch_version.strip() or not self.torch_cuda_version.strip():
            raise ValueError("CUDA evidence requires runtime version provenance")



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


def _torch_device_uuid(torch, index: int) -> str:
    value = getattr(torch.cuda.get_device_properties(index), "uuid", None)
    if value is None:
        raise RuntimeError(f"PyTorch did not expose a UUID for CUDA device {index}")
    return str(value)


def verify_cuda_runtime(*, output_path: str | Path) -> dict:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for real CUDA runtime verification") from exc

    if not bool(torch.cuda.is_available()):
        raise RuntimeError("CUDA runtime is not available")

    observation = probe_nvidia_host("local-gpu-verifier")
    expected = observation.gpu_count
    actual = int(torch.cuda.device_count())
    if expected < 1:
        raise RuntimeError("real CUDA verification requires at least one visible NVIDIA GPU")
    if actual != expected:
        raise RuntimeError(
            f"CUDA device count mismatch: observed {expected}, runtime {actual}"
        )

    observed_uuids = [gpu.uuid for gpu in observation.gpus]
    runtime_uuids: list[str] = []
    results: list[float] = []
    for index in range(expected):
        runtime_uuid = _torch_device_uuid(torch, index)
        runtime_uuids.append(runtime_uuid)
        torch.cuda.set_device(index)
        value = torch.tensor([1.0], device=f"cuda:{index}") * 3.0
        torch.cuda.synchronize(index)
        results.append(float(value.item()))

    if runtime_uuids != observed_uuids:
        raise RuntimeError(
            "CUDA runtime device identity mismatch: "
            f"observed {observed_uuids}, runtime {runtime_uuids}"
        )
    if any(result != 3.0 for result in results):
        raise RuntimeError(f"CUDA verification returned inconsistent per-GPU results: {results}")

    evidence = {
        "verification": "real_cuda_runtime",
        "recorded_at": int(time.time()),
        "torch_version": str(torch.__version__),
        "torch_cuda_version": str(torch.version.cuda),
        "device_count": expected,
        "gpu_uuids": observed_uuids,
        "runtime_gpu_uuids": runtime_uuids,
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
