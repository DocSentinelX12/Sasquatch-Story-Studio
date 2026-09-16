"""Fail-closed GPU allocation against observed worker hardware."""
from __future__ import annotations

import re
from itertools import combinations

from .gpu_infrastructure import GpuHostObservation
from .hardware_requirements import GpuPlacement, HardwareRequirements, compute_capability_at_least


def _topology_matrix(observation: GpuHostObservation) -> dict[tuple[str, str], str]:
    text = observation.topology_text or ""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return {}
    header_index = next((i for i, line in enumerate(lines) if re.search(r"\bGPU0\b", line)), None)
    if header_index is None:
        return {}
    headers = re.findall(r"GPU\d+", lines[header_index])
    if not headers:
        return {}
    matrix: dict[tuple[str, str], str] = {}
    for line in lines[header_index + 1 :]:
        match = re.match(r"^(GPU\d+)\s+(.*)$", line)
        if not match:
            continue
        source = match.group(1)
        values = re.split(r"\s+", match.group(2).strip())
        if len(values) < len(headers):
            continue
        for target, path in zip(headers, values):
            matrix[(source, target)] = path
    return matrix


def _candidate_gpus(observation: GpuHostObservation, requirements: HardwareRequirements, used_gpu_uuids: set[str]) -> list:
    candidates = []
    for gpu in observation.gpus:
        if gpu.uuid in used_gpu_uuids:
            continue
        if gpu.memory_total_mib * 1024**2 < requirements.min_vram_per_gpu_bytes:
            continue
        if requirements.min_compute_capability and not compute_capability_at_least(gpu.compute_capability, requirements.min_compute_capability):
            continue
        if requirements.required_gpu_models and gpu.name not in requirements.required_gpu_models:
            continue
        candidates.append(gpu)
    return candidates


def select_gpus(
    observation: GpuHostObservation,
    requirements: HardwareRequirements,
    *,
    used_gpu_uuids: set[str] | None = None,
) -> tuple[str, ...]:
    """Select physical GPU UUIDs; no topology or NCCL capability is inferred."""
    if requirements.placement is GpuPlacement.MULTI_NODE:
        raise RuntimeError("select_gpus is single-worker only; multi-node allocation requires cluster coordination")
    used = set(used_gpu_uuids or ())
    candidates = _candidate_gpus(observation, requirements, used)
    if len(candidates) < requirements.min_gpu_count:
        raise RuntimeError("observed worker lacks enough free GPUs satisfying the hardware contract")

    total_vram = sum(gpu.memory_total_mib * 1024**2 for gpu in candidates)
    if total_vram < requirements.min_total_vram_bytes:
        raise RuntimeError("observed free GPUs do not satisfy the total VRAM requirement")

    if requirements.placement is GpuPlacement.ANY:
        selected = candidates[: requirements.min_gpu_count]
    else:
        matrix = _topology_matrix(observation)
        by_index = {gpu.index: gpu for gpu in candidates}
        for group in combinations(candidates, requirements.min_gpu_count):
            if all(matrix.get((f"GPU{a.index}", f"GPU{b.index}"), "").startswith("NV") for a, b in combinations(group, 2)):
                selected = list(group)
                break
        else:
            raise RuntimeError("observed topology has no qualifying all-NVLink GPU group")

    if requirements.require_nccl:
        if not observation.dcgm_available:
            raise RuntimeError("NCCL requirement cannot be satisfied without observed DCGM/NCCL evidence")
        raise RuntimeError("NCCL placement requires an explicit NCCL capability observation; DCGM availability alone is insufficient")
    if requirements.require_gpu_direct_network:
        raise RuntimeError("GPU-direct network placement requires explicit network capability evidence")
    return tuple(gpu.uuid for gpu in selected)
