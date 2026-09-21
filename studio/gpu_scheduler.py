"""Fail-closed GPU allocation against observed worker hardware."""
from __future__ import annotations

import re
from itertools import combinations

from .gpu_capabilities import admit_gpu_workload, derive_gpu_capabilities
from .gpu_infrastructure import GpuHostObservation
from .hardware_requirements import GpuPlacement, HardwareRequirements


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
    """Select GPU UUIDs only after canonical capability eligibility is established."""
    if requirements.placement is GpuPlacement.MULTI_NODE:
        raise RuntimeError("select_gpus is single-worker only; multi-node allocation requires cluster coordination")

    used = set(used_gpu_uuids or ())
    now = max(
        (
            gpu.telemetry.collected_at
            for gpu in observation.gpus
            if gpu.telemetry is not None
        ),
        default=0,
    )
    capabilities = derive_gpu_capabilities(observation, now=now)
    candidates = [
        gpu for gpu in sorted(observation.gpus, key=lambda item: (item.index, item.uuid))
        if gpu.uuid not in used
        and capabilities.get(gpu.uuid).production_eligible
        and gpu.memory_total_mib * 1024**2 >= requirements.min_vram_per_gpu_bytes
        and (
            requirements.min_compute_capability is None
            or _compute_capability_at_least(gpu.compute_capability, requirements.min_compute_capability)
        )
        and (
            not requirements.required_gpu_models
            or gpu.name in requirements.required_gpu_models
        )
    ]

    if len(candidates) < requirements.min_gpu_count:
        raise RuntimeError("observed worker lacks enough free GPUs satisfying the canonical capability contract")

    selected: tuple[str, ...] | None = None
    if requirements.placement is GpuPlacement.ANY:
        selected = tuple(gpu.uuid for gpu in candidates[: requirements.min_gpu_count])
    else:
        topology = capabilities.get(candidates[0].uuid).topology_evidence
        if topology is None:
            raise RuntimeError("observed topology has no verified capability evidence")
        for group in combinations(candidates, requirements.min_gpu_count):
            group_uuids = tuple(gpu.uuid for gpu in group)
            if topology.same_nvlink_domain(group_uuids):
                selected = group_uuids
                break
        if selected is None:
            raise RuntimeError("observed topology has no qualifying all-NVLink GPU group")

    admitted = admit_gpu_workload(
        requirements,
        capabilities,
        selected_gpu_uuids=selected,
        now=now,
    )
    if admitted != selected:
        raise RuntimeError("selected GPUs do not satisfy canonical capability admission")
    return admitted


def _compute_capability_at_least(observed: str, required: str) -> bool:
    try:
        observed_parts = tuple(int(part) for part in observed.split("."))
        required_parts = tuple(int(part) for part in required.split("."))
    except ValueError:
        return False
    return observed_parts >= required_parts
