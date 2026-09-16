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
    """Select only GPUs backed by explicit host observations.

    This evaluator handles single-worker placement. Topology-sensitive and
    multi-node placement intentionally fail closed until their corresponding
    verified evidence and group scheduler exist.
    """
    if observation is None:
        return GpuPlacementDecision(False, (), "hardware observation is missing")
    if requirements.placement is GpuPlacement.SAME_NVLINK_DOMAIN:
        return GpuPlacementDecision(False, (), "same-NVLink-domain placement evidence is not verified")
    if requirements.placement is GpuPlacement.MULTI_NODE:
        return GpuPlacementDecision(False, (), "multi-node placement requires the distributed group scheduler")

    candidates = []
    for gpu in sorted(observation.gpus, key=lambda item: (item.index, item.uuid)):
        if requirements.min_vram_per_gpu_bytes and gpu.memory_total_mib * 1024**2 < requirements.min_vram_per_gpu_bytes:
            continue
        if requirements.min_compute_capability is not None:
            try:
                if not compute_capability_at_least(gpu.compute_capability, requirements.min_compute_capability):
                    continue
            except ValueError:
                continue
        if requirements.required_gpu_models and gpu.name not in requirements.required_gpu_models:
            continue
        candidates.append(gpu)

    if len(candidates) < requirements.min_gpu_count:
        return GpuPlacementDecision(False, (), "insufficient observed GPUs matching hardware requirements")

    selected = tuple(candidates[: requirements.min_gpu_count])
    total_vram = sum(gpu.memory_total_mib * 1024**2 for gpu in selected)
    if total_vram < requirements.min_total_vram_bytes:
        return GpuPlacementDecision(False, (), "insufficient total VRAM on selected GPUs")

    if requirements.require_nccl:
        evidence = observation.nccl_evidence
        if evidence is None:
            return GpuPlacementDecision(False, (), "NCCL evidence is missing")
        try:
            validate_nccl_evidence(evidence)
        except (ValueError, RuntimeError):
            return GpuPlacementDecision(False, (), "NCCL evidence is invalid")
        if tuple(evidence.gpu_uuids) != tuple(gpu.uuid for gpu in selected):
            return GpuPlacementDecision(False, (), "NCCL evidence does not match selected GPUs")
        if observation.topology_text is None:
            return GpuPlacementDecision(False, (), "NCCL topology evidence is missing")

    if requirements.require_gpu_direct_network:
        return GpuPlacementDecision(False, (), "GPU-direct network evidence is not verified")

    return GpuPlacementDecision(True, tuple(gpu.uuid for gpu in selected), "eligible")
