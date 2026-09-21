"""Fail-closed GPU placement evaluation from observed worker evidence."""
from __future__ import annotations

from dataclasses import dataclass

from .gpu_infrastructure import GpuHostObservation
from .hardware_requirements import GpuPlacement, HardwareRequirements, compute_capability_at_least
from .nccl_evidence import validate_nccl_evidence


@dataclass(frozen=True)
class GpuPlacementDecision:
    eligible: bool
    gpu_uuids: tuple[str, ...]
    reason: str


def evaluate_gpu_placement(
    requirements: HardwareRequirements,
    observation: GpuHostObservation | None,
) -> GpuPlacementDecision:
    """Evaluate placement through the canonical GPU capability authority."""
    if observation is None:
        return GpuPlacementDecision(False, (), "hardware observation is missing")
    if requirements.placement is GpuPlacement.MULTI_NODE:
        return GpuPlacementDecision(False, (), "multi-node placement requires the distributed group scheduler")
    try:
        from .gpu_scheduler import select_gpus
        selected = select_gpus(observation, requirements)
    except RuntimeError as exc:
        return GpuPlacementDecision(False, (), str(exc))
    return GpuPlacementDecision(True, selected, "eligible")
