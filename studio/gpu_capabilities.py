"""Canonical evidence-backed GPU capability derivation and workload admission."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from enum import StrEnum
from typing import Mapping

from .gpu_infrastructure import GpuHostObservation, classify_dcgm_health
from .hardware_requirements import GpuPlacement, HardwareRequirements, compute_capability_at_least
from .nccl_evidence import validate_nccl_evidence


class GpuCapabilityName(StrEnum):
    BASE_GPU = "base_gpu"
    CUDA_RUNTIME = "cuda_runtime"
    HEALTH = "health"
    TOPOLOGY_NVLINK = "topology_nvlink"
    NCCL = "nccl"
    GPU_DIRECT_NETWORK = "gpu_direct_network"
    ENGINE_RUNTIME = "engine_runtime"


class GpuCapabilityState(StrEnum):
    IDENTIFIED = "identified"
    VERIFIED = "verified"
    DEGRADED = "degraded"
    PRODUCTION_ELIGIBLE = "production_eligible"
    STALE = "stale"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GpuCapability:
    name: GpuCapabilityName
    state: GpuCapabilityState
    evidence_digest: str
    observed_at: int | None = None
    verified_at: int | None = None
    detail: str = ""

    @property
    def admissible(self) -> bool:
        return self.state in {
            GpuCapabilityState.VERIFIED,
            GpuCapabilityState.PRODUCTION_ELIGIBLE,
        }


@dataclass(frozen=True)
class GpuCapabilityRecord:
    worker_id: str
    gpu_uuid: str
    observation_digest: str
    capabilities: tuple[GpuCapability, ...]
    memory_total_mib: int
    name: str
    compute_capability: str
    topology_evidence: object | None = None
    nccl_gpu_sets: tuple[tuple[str, ...], ...] = ()
    gpu_direct_gpu_sets: tuple[tuple[str, ...], ...] = ()

    def state(self, name: GpuCapabilityName) -> GpuCapabilityState:
        for capability in self.capabilities:
            if capability.name is name:
                return capability.state
        return GpuCapabilityState.UNAVAILABLE

    def capability(self, name: GpuCapabilityName) -> GpuCapability:
        for capability in self.capabilities:
            if capability.name is name:
                return capability
        raise KeyError(name)

    @property
    def production_eligible(self) -> bool:
        return (
            self.state(GpuCapabilityName.BASE_GPU) is GpuCapabilityState.IDENTIFIED
            and self.state(GpuCapabilityName.HEALTH) is GpuCapabilityState.VERIFIED
        )


@dataclass(frozen=True)
class GpuCapabilitySet:
    records: tuple[GpuCapabilityRecord, ...]

    def __post_init__(self) -> None:
        uuids = tuple(record.gpu_uuid for record in self.records)
        if len(set(uuids)) != len(uuids):
            raise ValueError("GPU capability UUIDs must be unique")

    def canonical_json(self) -> str:
        payload = {
            "records": [
                {
                    "worker_id": record.worker_id,
                    "gpu_uuid": record.gpu_uuid,
                    "observation_digest": record.observation_digest,
                    "memory_total_mib": record.memory_total_mib,
                    "name": record.name,
                    "compute_capability": record.compute_capability,
                    "capabilities": [asdict(capability) for capability in record.capabilities],
                    "nccl_gpu_sets": [list(group) for group in record.nccl_gpu_sets],
                    "gpu_direct_gpu_sets": [list(group) for group in record.gpu_direct_gpu_sets],
                }
                for record in self.records
            ]
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def get(self, gpu_uuid: str) -> GpuCapabilityRecord:
        for record in self.records:
            if record.gpu_uuid == gpu_uuid:
                return record
        raise KeyError(f"unknown GPU capability: {gpu_uuid}")


def _observation_timestamp(observation: GpuHostObservation) -> int | None:
    timestamps = [
        gpu.telemetry.collected_at
        for gpu in observation.gpus
        if gpu.telemetry is not None
    ]
    return min(timestamps) if timestamps else None


def _state_for_timestamp(
    state: GpuCapabilityState,
    observed_at: int | None,
    *,
    now: int,
    freshness_window_seconds: int | None,
) -> GpuCapabilityState:
    if freshness_window_seconds is None or observed_at is None:
        return state
    if freshness_window_seconds < 0:
        raise ValueError("freshness_window_seconds cannot be negative")
    if observed_at > now or now - observed_at > freshness_window_seconds:
        return GpuCapabilityState.STALE
    return state


def _engine_timestamp(value: object) -> int | None:
    if isinstance(value, int):
        return value
    recorded_at = getattr(value, "recorded_at", None)
    return int(recorded_at) if isinstance(recorded_at, int) else None


def derive_gpu_capabilities(
    observation: GpuHostObservation,
    *,
    now: int,
    freshness_window_seconds: int | None = None,
    engine_verifications: Mapping[str, object] | None = None,
    gpu_direct_gpu_sets: tuple[tuple[str, ...], ...] = (),
) -> GpuCapabilitySet:
    if now < 0:
        raise ValueError("now cannot be negative")
    observation_digest = observation.digest()
    observed_at = _observation_timestamp(observation)
    health_state = {
        "healthy": GpuCapabilityState.VERIFIED,
        "warning": GpuCapabilityState.DEGRADED,
        "failure": GpuCapabilityState.FAILED,
        "unknown": GpuCapabilityState.UNAVAILABLE,
    }[classify_dcgm_health(observation.health_json)]
    health_state = _state_for_timestamp(
        health_state,
        observed_at,
        now=now,
        freshness_window_seconds=freshness_window_seconds,
    )

    topology_state = (
        GpuCapabilityState.VERIFIED
        if observation.topology_evidence is not None
        else GpuCapabilityState.UNAVAILABLE
    )
    topology_state = _state_for_timestamp(
        topology_state,
        observed_at,
        now=now,
        freshness_window_seconds=freshness_window_seconds,
    )

    try:
        if observation.nccl_evidence is None:
            nccl_state = GpuCapabilityState.UNAVAILABLE
        else:
            validate_nccl_evidence(observation.nccl_evidence)
            nccl_state = GpuCapabilityState.VERIFIED
    except (ValueError, RuntimeError) as exc:
        nccl_state = GpuCapabilityState.FAILED
        nccl_detail = str(exc)
    else:
        nccl_detail = ""

    nccl_state = _state_for_timestamp(
        nccl_state,
        observed_at,
        now=now,
        freshness_window_seconds=freshness_window_seconds,
    )

    records = []
    for gpu in observation.gpus:
        engine_caps = []
        for engine_id, verification in (engine_verifications or {}).items():
            timestamp = _engine_timestamp(verification)
            state = (
                GpuCapabilityState.VERIFIED
                if timestamp is not None
                else GpuCapabilityState.UNAVAILABLE
            )
            state = _state_for_timestamp(
                state,
                timestamp,
                now=now,
                freshness_window_seconds=freshness_window_seconds,
            )
            engine_caps.append(
                GpuCapability(
                    GpuCapabilityName.ENGINE_RUNTIME,
                    state,
                    observation_digest,
                    timestamp,
                    timestamp if state is GpuCapabilityState.VERIFIED else None,
                    engine_id,
                )
            )

        capabilities = (
            GpuCapability(
                GpuCapabilityName.BASE_GPU,
                GpuCapabilityState.IDENTIFIED,
                observation_digest,
                observed_at,
                None,
                "physical GPU identity and inventory observed",
            ),
            GpuCapability(
                GpuCapabilityName.CUDA_RUNTIME,
                GpuCapabilityState.IDENTIFIED,
                observation_digest,
                observed_at,
                None,
                "driver and supported CUDA versions observed; runtime execution not inferred",
            ),
            GpuCapability(
                GpuCapabilityName.HEALTH,
                health_state,
                observation_digest,
                observed_at,
                observed_at if health_state is GpuCapabilityState.VERIFIED else None,
                "DCGM health evidence",
            ),
            GpuCapability(
                GpuCapabilityName.TOPOLOGY_NVLINK,
                topology_state,
                observation_digest,
                observed_at,
                observed_at if topology_state is GpuCapabilityState.VERIFIED else None,
                "observed topology evidence",
            ),
            GpuCapability(
                GpuCapabilityName.NCCL,
                nccl_state,
                observation_digest,
                observed_at,
                observed_at if nccl_state is GpuCapabilityState.VERIFIED else None,
                locals().get("nccl_detail", ""),
            ),
            GpuCapability(
                GpuCapabilityName.GPU_DIRECT_NETWORK,
                (
                    GpuCapabilityState.VERIFIED
                    if any(gpu.uuid in group for group in gpu_direct_gpu_sets)
                    else GpuCapabilityState.UNAVAILABLE
                ),
                observation_digest,
                observed_at,
                observed_at if any(gpu.uuid in group for group in gpu_direct_gpu_sets) else None,
                "explicit GPU-direct verification set" if gpu_direct_gpu_sets else "",
            ),
            *engine_caps,
        )
        records.append(
            GpuCapabilityRecord(
                worker_id=observation.worker_id,
                gpu_uuid=gpu.uuid,
                observation_digest=observation_digest,
                capabilities=capabilities,
                memory_total_mib=gpu.memory_total_mib,
                name=gpu.name,
                compute_capability=gpu.compute_capability,
                topology_evidence=observation.topology_evidence,
                nccl_gpu_sets=(
                    (tuple(observation.nccl_evidence.gpu_uuids),)
                    if observation.nccl_evidence is not None and nccl_state is GpuCapabilityState.VERIFIED
                    else ()
                ),
                gpu_direct_gpu_sets=tuple(tuple(group) for group in gpu_direct_gpu_sets),
            )
        )

    return GpuCapabilitySet(tuple(records))


def _requirements_match_gpu(requirements: HardwareRequirements, record: GpuCapabilityRecord) -> bool:
    if not record.production_eligible:
        return False
    if record.state(GpuCapabilityName.CUDA_RUNTIME) is GpuCapabilityState.FAILED:
        return False
    if record.memory_total_mib * 1024 * 1024 < requirements.min_vram_per_gpu_bytes:
        return False
    if requirements.min_compute_capability is not None and not compute_capability_at_least(
        record.compute_capability,
        requirements.min_compute_capability,
    ):
        return False
    if requirements.required_gpu_models and record.name not in requirements.required_gpu_models:
        return False
    return True


def admit_gpu_workload(
    requirements: HardwareRequirements,
    capabilities: GpuCapabilitySet,
    *,
    selected_gpu_uuids: tuple[str, ...],
    now: int,
    required_engine_id: str | None = None,
) -> tuple[str, ...]:
    if now < 0:
        raise ValueError("now cannot be negative")
    if len(selected_gpu_uuids) != len(set(selected_gpu_uuids)):
        return ()
    if len(selected_gpu_uuids) < requirements.min_gpu_count:
        return ()
    try:
        records = tuple(capabilities.get(uuid) for uuid in selected_gpu_uuids)
    except KeyError:
        return ()
    if any(not _requirements_match_gpu(requirements, record) for record in records):
        return ()

    if sum(record.memory_total_mib * 1024 * 1024 for record in records) < requirements.min_total_vram_bytes:
        return ()

    if required_engine_id is not None:
        for record in records:
            if not any(
                capability.name is GpuCapabilityName.ENGINE_RUNTIME
                and capability.detail == required_engine_id
                and capability.admissible
                for capability in record.capabilities
            ):
                return ()

    if requirements.placement is GpuPlacement.SAME_NVLINK_DOMAIN:
        topology = records[0].topology_evidence
        if topology is None or not topology.same_nvlink_domain(selected_gpu_uuids):
            return ()

    if requirements.placement is GpuPlacement.MULTI_NODE:
        if len({record.worker_id for record in records}) < 2:
            return ()

    if requirements.require_nccl:
        if not all(record.state(GpuCapabilityName.NCCL) is GpuCapabilityState.VERIFIED for record in records):
            return ()
        if not any(set(group) == set(selected_gpu_uuids) for group in records[0].nccl_gpu_sets):
            return ()

    if requirements.require_gpu_direct_network:
        if not any(set(group) == set(selected_gpu_uuids) for group in records[0].gpu_direct_gpu_sets):
            return ()

    return selected_gpu_uuids
