"""Fail-closed GPU placement evaluation from observed worker evidence."""
from __future__ import annotations

from dataclasses import dataclass

from .gpu_capabilities import admit_gpu_workload, derive_gpu_capabilities
from .gpu_infrastructure import GpuHostObservation
from .hardware_requirements import GpuPlacement, HardwareRequirements


@dataclass(frozen=True)
class GpuPlacementDecision:
    eligible: bool
    gpu_uuids: tuple[str, ...]
    reason: str


def evaluate_gpu_placement(
    requirements: HardwareRequirements,
    observation: GpuHostObservation | None,
    *,
    now: int = 0,
) -> GpuPlacementDecision:
    """Compatibility placement facade backed by canonical GPU capability admission."""
    if observation is None:
        return GpuPlacementDecision(False, (), "hardware observation is missing")
    if requirements.placement is GpuPlacement.MULTI_NODE:
        return GpuPlacementDecision(False, (), "multi-node placement requires the distributed group scheduler")
    capabilities = derive_gpu_capabilities(observation, now)
    decision = admit_gpu_workload(requirements, capabilities, now)
    return GpuPlacementDecision(decision.eligible, decision.gpu_uuids, decision.reason)
