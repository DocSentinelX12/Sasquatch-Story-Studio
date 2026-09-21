"""Canonical, evidence-backed GPU capability state and workload admission."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .gpu_infrastructure import GpuHostObservation, TelemetryStatus, classify_dcgm_health
from .gpu_topology import GpuTopologyEvidence, parse_nvidia_smi_topology
from .hardware_requirements import GpuPlacement, HardwareRequirements, compute_capability_at_least
from .nccl_evidence import validate_nccl_evidence
from .network_evidence import NetworkFabricObservation


class CapabilityState(StrEnum):
    OBSERVED = "observed"
    VERIFIED = "verified"
    DEGRADED = "degraded"
    STALE = "stale"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CapabilityEvidence:
    state: CapabilityState
    reason: str
    evidence_digest: str | None
    verified_at: int | None
    fresh_until: int | None

    def is_admissible(self, now: int, freshness_seconds: int | None = None) -> bool:
        if self.state is not CapabilityState.VERIFIED:
            return False
        if freshness_seconds is not None:
            if self.verified_at is None or now - self.verified_at < 0 or now - self.verified_at > freshness_seconds:
                return False
        elif self.fresh_until is not None and now > self.fresh_until:
            return False
        return True


@dataclass(frozen=True)
class GpuCapabilityRecord:
    worker_id: str
    gpu_uuid: str
    model: str
    memory_total_mib: int
    compute_capability: str
    base: CapabilityEvidence
    cuda_runtime: CapabilityEvidence
    health: CapabilityEvidence
    topology: CapabilityEvidence
    nccl: CapabilityEvidence
    gpu_direct: CapabilityEvidence
    engine_runtime: CapabilityEvidence
    observation_digest: str
    observed_at: int

    def __post_init__(self) -> None:
        if not self.worker_id.strip() or not self.gpu_uuid.strip() or not self.model.strip():
            raise ValueError("GPU capability identity is required")
        if self.memory_total_mib < 0:
            raise ValueError("GPU memory cannot be negative")
        if len(self.observation_digest) != 64 or any(c not in "0123456789abcdef" for c in self.observation_digest.lower()):
            raise ValueError("observation_digest must be SHA-256")
        if self.observed_at < 0:
            raise ValueError("observed_at cannot be negative")


@dataclass(frozen=True)
class GpuVerificationContext:
    network: NetworkFabricObservation | None = None
    engine_verified: bool = False
    engine_id: str | None = None
    engine_evidence_digest: str | None = None


@dataclass(frozen=True)
class GpuCapabilitySet:
    records: tuple[GpuCapabilityRecord, ...]
    topology_evidence: GpuTopologyEvidence | None
    network_evidence: NetworkFabricObservation | None
    nccl_gpu_uuids: tuple[str, ...]
    observation_digest: str
    observed_at: int

    def __post_init__(self) -> None:
        uuids = tuple(record.gpu_uuid for record in self.records)
        if len(set(uuids)) != len(uuids):
            raise ValueError("GPU capability UUIDs must be unique")


@dataclass(frozen=True)
class GpuAdmissionDecision:
    eligible: bool
    gpu_uuids: tuple[str, ...]
    reason: str

def _derive_topology_evidence(observation: GpuHostObservation) -> GpuTopologyEvidence | None:
    if observation.topology_evidence is not None:
        return observation.topology_evidence
    if not observation.topology_text:
        return None
    try:
        return parse_nvidia_smi_topology(
            observation.topology_text,
            {gpu.index: gpu.uuid for gpu in observation.gpus},
        )
    except ValueError:
        lines = [line.strip() for line in observation.topology_text.splitlines() if line.strip()]
        if not lines:
            return None
        header = re.findall(r"GPU\d+", lines[0])
        if not header:
            return None
        indices = [int(token[3:]) for token in header]
        known = {gpu.index for gpu in observation.gpus}
        if len(indices) != len(set(indices)) or any(index not in known for index in indices):
            return None
        rows = {}
        for line in lines[1:]:
            parts = line.split()
            if not parts or not re.fullmatch(r"GPU\d+", parts[0]):
                continue
            row_index = int(parts[0][3:])
            if row_index in indices and len(parts[1:]) == len(indices):
                rows[row_index] = tuple(parts[1:])
        if set(rows) != set(indices):
            return None
        ordered = tuple(next(gpu.uuid for gpu in observation.gpus if gpu.index == index) for index in indices)
        return GpuTopologyEvidence(
            gpu_uuids=ordered,
            gpu_matrix=tuple(rows[index] for index in indices),
            cpu_affinity=(),
            nic_paths=(),
            raw_text_sha256=hashlib.sha256(observation.topology_text.encode("utf-8")).hexdigest(),
        )



def _evidence(state: CapabilityState, reason: str, digest: str | None, verified_at: int | None, freshness_seconds: int | None) -> CapabilityEvidence:
    fresh_until = None if verified_at is None or freshness_seconds is None else verified_at + freshness_seconds
    return CapabilityEvidence(state, reason, digest, verified_at, fresh_until)


def _digest(value: str | None) -> str | None:
    return value if value else None


def derive_gpu_capabilities(
    observation: GpuHostObservation,
    now: int,
    verification_context: GpuVerificationContext | None = None,
) -> GpuCapabilitySet:
    if now < 0:
        raise ValueError("now cannot be negative")
    context = verification_context or GpuVerificationContext()
    topology_evidence = _derive_topology_evidence(observation)
    records: list[GpuCapabilityRecord] = []
    for gpu in observation.gpus:
        base_ok = bool(gpu.uuid.strip() and gpu.name.strip() and gpu.memory_total_mib > 0)
        try:
            compute_ok = bool(gpu.compute_capability.strip())
            compute_capability_at_least(gpu.compute_capability, gpu.compute_capability)
        except ValueError:
            compute_ok = False
        base_state = CapabilityState.VERIFIED if base_ok and compute_ok else CapabilityState.FAILED
        cuda_state = CapabilityState.VERIFIED if observation.cuda_supported_version.strip() and observation.driver_version.strip() else CapabilityState.FAILED

        health_evidence = gpu.telemetry.dcgm_health
        health_state = health_evidence.value if health_evidence.status is TelemetryStatus.OBSERVED else classify_dcgm_health(observation.health_json)
        health_source = health_evidence.source if health_evidence.status is TelemetryStatus.OBSERVED else "dcgm_health_json"
        if health_state == "healthy":
            health = _evidence(CapabilityState.VERIFIED, f"DCGM reported healthy via {health_source}", observation.digest(), observation.observed_at, None)
        elif health_state == "warning":
            health = _evidence(CapabilityState.DEGRADED, f"DCGM reported warning via {health_source}", observation.digest(), observation.observed_at, None)
        elif health_state == "failure":
            health = _evidence(CapabilityState.FAILED, f"DCGM reported failure via {health_source}", observation.digest(), observation.observed_at, None)
        else:
            health = _evidence(CapabilityState.OBSERVED, "health evidence is not verified", None, None, None)

        if topology_evidence is not None and gpu.uuid in topology_evidence.gpu_uuids:
            topology = _evidence(CapabilityState.VERIFIED, "observed NVIDIA topology evidence covers GPU", topology_evidence.raw_text_sha256, observation.observed_at, None)
        else:
            topology = _evidence(CapabilityState.UNSUPPORTED, "verified topology evidence is unavailable", None, None, None)

        if observation.nccl_evidence is not None and gpu.uuid in observation.nccl_evidence.gpu_uuids:
            try:
                validate_nccl_evidence(observation.nccl_evidence)
            except (ValueError, RuntimeError):
                nccl = _evidence(CapabilityState.FAILED, "NCCL evidence is invalid", None, None, None)
            else:
                nccl = _evidence(CapabilityState.VERIFIED, "validated NCCL evidence covers GPU", observation.nccl_evidence.output_sha256, observation.observed_at, None)
        else:
            nccl = _evidence(CapabilityState.OBSERVED, "NCCL evidence does not cover GPU", None, None, None)

        if context.network is not None and context.network.gpu_direct_rdma:
            gpu_direct = _evidence(CapabilityState.VERIFIED, "explicit GPU-direct RDMA evidence is present", None, observation.observed_at, None)
        else:
            gpu_direct = _evidence(CapabilityState.OBSERVED, "GPU-direct evidence is not verified", None, None, None)

        if context.engine_verified and context.engine_id and context.engine_evidence_digest:
            engine_runtime = _evidence(
                CapabilityState.VERIFIED,
                f"engine runtime evidence verified for {context.engine_id}",
                context.engine_evidence_digest,
                observation.observed_at,
                None,
            )
        else:
            engine_runtime = _evidence(CapabilityState.OBSERVED, "engine runtime evidence is not verified", None, None, None)

        records.append(
            GpuCapabilityRecord(
                worker_id=observation.worker_id,
                gpu_uuid=gpu.uuid,
                model=gpu.name,
                memory_total_mib=gpu.memory_total_mib,
                compute_capability=gpu.compute_capability,
                base=_evidence(base_state, "physical GPU identity and inventory observed" if base_state is CapabilityState.VERIFIED else "GPU base inventory is invalid", observation.digest(), observation.observed_at, None),
                cuda_runtime=_evidence(cuda_state, "driver and CUDA versions observed" if cuda_state is CapabilityState.VERIFIED else "CUDA runtime evidence is incomplete", observation.digest(), observation.observed_at, None),
                health=health,
                topology=topology,
                nccl=nccl,
                gpu_direct=gpu_direct,
                engine_runtime=engine_runtime,
                observation_digest=observation.digest(),
                observed_at=observation.observed_at,
            )
        )
    return GpuCapabilitySet(
        tuple(records),
        topology_evidence,
        context.network,
        tuple(sorted(observation.nccl_evidence.gpu_uuids)) if observation.nccl_evidence is not None else (),
        observation.digest(),
        observation.observed_at,
    )


def _freshness_failure(evidence: CapabilityEvidence, name: str, now: int, freshness_seconds: int | None) -> str | None:
    if evidence.state is not CapabilityState.VERIFIED:
        return f"{name} capability is {evidence.state.value}"
    if not evidence.is_admissible(now, freshness_seconds):
        return f"{name} capability is stale"
    return None


def admit_gpu_workload(
    requirements: HardwareRequirements,
    capabilities: GpuCapabilitySet,
    now: int,
    *,
    freshness_seconds: Mapping[str, int] | None = None,
) -> GpuAdmissionDecision:
    freshness = freshness_seconds or {}
    candidates: list[GpuCapabilityRecord] = []
    for record in capabilities.records:
        if record.memory_total_mib * 1024**2 < requirements.min_vram_per_gpu_bytes:
            continue
        try:
            if requirements.min_compute_capability is not None and not compute_capability_at_least(record.compute_capability, requirements.min_compute_capability):
                continue
        except ValueError:
            continue
        if requirements.required_gpu_models and record.model not in requirements.required_gpu_models:
            continue
        for name in ("base", "cuda_runtime"):
            failure = _freshness_failure(getattr(record, name), name, now, freshness.get(name))
            if failure:
                break
        else:
            candidates.append(record)
    if len(candidates) < requirements.min_gpu_count:
        return GpuAdmissionDecision(False, (), "no sufficient set of GPUs satisfies the canonical base capability contract")

    if requirements.placement is GpuPlacement.SAME_NVLINK_DOMAIN:
        if capabilities.topology_evidence is None:
            return GpuAdmissionDecision(False, (), "topology capability is unavailable")
        selected = None
        from itertools import combinations
        for group in combinations(candidates, requirements.min_gpu_count):
            uuids = tuple(item.gpu_uuid for item in group)
            if capabilities.topology_evidence.same_nvlink_domain(uuids):
                selected = group
                break
        if selected is None:
            return GpuAdmissionDecision(False, (), "topology capability cannot satisfy the requested NVLink domain")
    else:
        selected = tuple(candidates[: requirements.min_gpu_count])

    selected_uuids = tuple(item.gpu_uuid for item in selected)
    total_vram = sum(item.memory_total_mib * 1024**2 for item in selected)
    if total_vram < requirements.min_total_vram_bytes:
        return GpuAdmissionDecision(False, (), "selected GPUs do not satisfy total VRAM")

    if "health" in freshness:
        if any(_freshness_failure(item.health, "health", now, freshness["health"]) for item in selected):
            return GpuAdmissionDecision(False, (), "health capability is missing, failed, degraded, or stale")

    if requirements.require_nccl:
        if any(_freshness_failure(item.nccl, "NCCL", now, freshness.get("nccl")) for item in selected):
            return GpuAdmissionDecision(False, (), "NCCL capability is missing, failed, or stale")
        if capabilities.nccl_gpu_uuids != tuple(sorted(selected_uuids)):
            return GpuAdmissionDecision(False, (), "NCCL evidence does not exactly cover the selected GPU set")

    if requirements.require_gpu_direct_network:
        if capabilities.network_evidence is None or not capabilities.network_evidence.gpu_direct_rdma:
            return GpuAdmissionDecision(False, (), "GPU-direct capability is unavailable")

    return GpuAdmissionDecision(True, selected_uuids, "eligible")
