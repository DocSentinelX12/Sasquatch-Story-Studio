"""Fail-closed GPU allocation against observed worker hardware."""
from __future__ import annotations

from dataclasses import replace

from .gpu_capabilities import admit_gpu_workload, derive_gpu_capabilities
from .gpu_infrastructure import GpuHostObservation
from .hardware_requirements import GpuPlacement, HardwareRequirements


def select_gpus(
    observation: GpuHostObservation,
    requirements: HardwareRequirements,
    *,
    used_gpu_uuids: set[str] | None = None,
    now: int = 0,
) -> tuple[str, ...]:
    """Select physical GPU UUIDs through the canonical capability authority."""
    if requirements.placement is GpuPlacement.MULTI_NODE:
        raise RuntimeError("select_gpus is single-worker only; multi-node allocation requires cluster coordination")
    used = set(used_gpu_uuids or ())
    capabilities = derive_gpu_capabilities(observation, now)
    if used:
        capabilities = replace(
            capabilities,
            records=tuple(record for record in capabilities.records if record.gpu_uuid not in used),
        )
    decision = admit_gpu_workload(requirements, capabilities, now)
    if not decision.eligible:
        raise RuntimeError(decision.reason)
    return decision.gpu_uuids
