"""Explicit hardware placement contracts for GPU production workloads."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GpuPlacement(StrEnum):
    ANY = "any"
    SAME_NVLINK_DOMAIN = "same_nvlink_domain"
    MULTI_NODE = "multi_node"


@dataclass(frozen=True)
class HardwareRequirements:
    """Minimum observed hardware evidence required before scheduling a task.

    The scheduler may satisfy these requirements only from actual worker
    observations. It must never infer topology, NCCL support, or multi-node
    capability from GPU count alone.
    """

    min_gpu_count: int = 1
    min_vram_per_gpu_bytes: int = 0
    min_total_vram_bytes: int = 0
    min_compute_capability: str | None = None
    required_gpu_models: tuple[str, ...] = ()
    placement: GpuPlacement = GpuPlacement.ANY
    require_nccl: bool = False
    allow_multi_node: bool = False
    require_gpu_direct_network: bool = False

    def __post_init__(self) -> None:
        if self.min_gpu_count < 1:
            raise ValueError("min_gpu_count must be positive")
        if self.min_vram_per_gpu_bytes < 0 or self.min_total_vram_bytes < 0:
            raise ValueError("VRAM requirements cannot be negative")
        if self.placement is GpuPlacement.MULTI_NODE and not self.allow_multi_node:
            raise ValueError("multi-node placement requires allow_multi_node=True")
        if self.placement is not GpuPlacement.MULTI_NODE and self.allow_multi_node:
            raise ValueError("allow_multi_node is only valid for multi-node placement")
        if self.min_compute_capability is not None:
            _parse_compute_capability(self.min_compute_capability)
        if any(not model.strip() for model in self.required_gpu_models):
            raise ValueError("required GPU model names cannot be empty")


def _parse_compute_capability(value: str) -> tuple[int, int]:
    parts = value.split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("compute capability must use major.minor notation")
    return int(parts[0]), int(parts[1])


def compute_capability_at_least(observed: str, required: str) -> bool:
    """Compare CUDA compute capabilities without guessing unknown formats."""
    return _parse_compute_capability(observed) >= _parse_compute_capability(required)
