"""Durable registry for observed heterogeneous compute workers."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from .gpu_capabilities import GpuCapabilitySet, GpuCapabilityRecord, CapabilityEvidence, CapabilityState
from .gpu_infrastructure import GpuDeviceObservation, GpuHostObservation, GpuTelemetryObservation, TelemetryEvidence, TelemetryStatus
from .gpu_topology import GpuTopologyEvidence
from .nccl_evidence import NCCLTestEvidence
from .resources import ComputeResource


class WorkerState(StrEnum):
    VERIFIED_AVAILABLE = "verified_available"
    VERIFIED_LIMITED = "verified_available_with_limits"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    QUOTA_EXHAUSTED = "quota_exhausted"
    OFFLINE = "offline"
    CAPABILITY_MISMATCH = "capability_mismatch"
    UNVERIFIED = "unverified"
    RETIRED = "retired"


@dataclass(frozen=True)
class WorkerRecord:
    id: str
    resource: ComputeResource
    state: WorkerState = WorkerState.UNVERIFIED
    observed_at: int | None = None
    observation_source: str = ""
    quota_note: str = ""
    hardware_observation: GpuHostObservation | None = None
    gpu_capabilities: GpuCapabilitySet | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("worker id is required")
        if not self.resource.id.strip():
            raise ValueError("worker resource id is required")
        if self.hardware_observation is not None and self.hardware_observation.worker_id != self.id:
            raise ValueError("hardware observation worker identity must match record")


class WorkerRegistry:
    """In-memory authoritative registry; persistence is supplied separately."""

    def __init__(self, records: tuple[WorkerRecord, ...] = ()):
        self._records = {record.id: record for record in records}

    def register(self, record: WorkerRecord) -> None:
        if record.id in self._records:
            raise ValueError(f"worker already exists: {record.id}")
        self._records[record.id] = record

    def update(self, record: WorkerRecord) -> None:
        if record.id not in self._records:
            raise KeyError(f"unknown worker: {record.id}")
        self._records[record.id] = record

    def get(self, worker_id: str) -> WorkerRecord:
        try:
            return self._records[worker_id]
        except KeyError as exc:
            raise KeyError(f"unknown worker: {worker_id}") from exc

    def snapshot(self) -> tuple[WorkerRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def mark_unavailable(self, worker_id: str, state: WorkerState, observed_at: int | None = None, quota_note: str | None = None) -> WorkerRecord:
        if state not in {WorkerState.TEMPORARILY_UNAVAILABLE, WorkerState.QUOTA_EXHAUSTED, WorkerState.OFFLINE}:
            raise ValueError("mark_unavailable requires an unavailable worker state")
        current = self.get(worker_id)
        updated = WorkerRecord(
            current.id,
            current.resource,
            state,
            observed_at,
            current.observation_source,
            current.quota_note if quota_note is None else quota_note,
            current.hardware_observation,
        )
        self._records[worker_id] = updated
        return updated


def _serialize_capabilities(capabilities: GpuCapabilitySet | None) -> dict | None:
    if capabilities is None:
        return None
    return asdict(capabilities)


def _deserialize_capabilities(payload: dict | None) -> GpuCapabilitySet | None:
    if payload is None:
        return None
    records = []
    for raw in payload["records"]:
        def evidence(value: dict) -> CapabilityEvidence:
            return CapabilityEvidence(
                state=CapabilityState(value["state"]),
                reason=value["reason"],
                evidence_digest=value.get("evidence_digest"),
                verified_at=value.get("verified_at"),
                fresh_until=value.get("fresh_until"),
            )
        records.append(
            GpuCapabilityRecord(
                worker_id=raw["worker_id"],
                gpu_uuid=raw["gpu_uuid"],
                model=raw["model"],
                memory_total_mib=int(raw["memory_total_mib"]),
                compute_capability=raw["compute_capability"],
                base=evidence(raw["base"]),
                cuda_runtime=evidence(raw["cuda_runtime"]),
                health=evidence(raw["health"]),
                topology=evidence(raw["topology"]),
                nccl=evidence(raw["nccl"]),
                gpu_direct=evidence(raw["gpu_direct"]),
                observation_digest=raw["observation_digest"],
                observed_at=int(raw["observed_at"]),
            )
        )
    network_payload = payload.get("network_evidence")
    network = None
    if network_payload is not None:
        from .network_evidence import NetworkFabricObservation
        network = NetworkFabricObservation(**network_payload)
    topology_payload = payload.get("topology_evidence")
    topology = None
    if topology_payload is not None:
        topology = GpuTopologyEvidence(
            gpu_uuids=tuple(topology_payload["gpu_uuids"]),
            gpu_matrix=tuple(tuple(row) for row in topology_payload["gpu_matrix"]),
            cpu_affinity=tuple(tuple(item) for item in topology_payload["cpu_affinity"]),
            nic_paths=tuple(tuple(item) for item in topology_payload["nic_paths"]),
            raw_text_sha256=topology_payload["raw_text_sha256"],
        )
    return GpuCapabilitySet(
        records=tuple(records),
        topology_evidence=topology,
        network_evidence=network,
        nccl_gpu_uuids=tuple(payload.get("nccl_gpu_uuids", ())),
        observation_digest=payload["observation_digest"],
        observed_at=int(payload["observed_at"]),
    )


def _serialize_observation(observation: GpuHostObservation | None) -> dict | None:
    if observation is None:
        return None
    payload = asdict(observation)
    if observation.nccl_evidence is not None:
        payload["nccl_evidence"]["command"] = list(observation.nccl_evidence.command)
        payload["nccl_evidence"]["gpu_uuids"] = list(observation.nccl_evidence.gpu_uuids)
    if observation.topology_evidence is not None:
        payload["topology_evidence"]["gpu_uuids"] = list(observation.topology_evidence.gpu_uuids)
        payload["topology_evidence"]["gpu_matrix"] = [list(row) for row in observation.topology_evidence.gpu_matrix]
        payload["topology_evidence"]["cpu_affinity"] = [list(item) for item in observation.topology_evidence.cpu_affinity]
        payload["topology_evidence"]["nic_paths"] = [list(item) for item in observation.topology_evidence.nic_paths]
    return payload


def _deserialize_observation(payload: dict | None) -> GpuHostObservation | None:
    if payload is None:
        return None
    topology_payload = payload.get("topology_evidence")
    topology_evidence = None
    if topology_payload is not None:
        topology_evidence = GpuTopologyEvidence(
            gpu_uuids=tuple(topology_payload["gpu_uuids"]),
            gpu_matrix=tuple(tuple(row) for row in topology_payload["gpu_matrix"]),
            cpu_affinity=tuple(tuple(item) for item in topology_payload["cpu_affinity"]),
            nic_paths=tuple(tuple(item) for item in topology_payload["nic_paths"]),
            raw_text_sha256=topology_payload["raw_text_sha256"],
        )
    nccl_payload = payload.get("nccl_evidence")
    nccl_evidence = None
    if nccl_payload is not None:
        nccl_evidence = NCCLTestEvidence(
            executable=nccl_payload["executable"],
            executable_sha256=nccl_payload["executable_sha256"],
            command=tuple(nccl_payload["command"]),
            exit_code=nccl_payload["exit_code"],
            output_sha256=nccl_payload["output_sha256"],
            gpu_uuids=tuple(nccl_payload["gpu_uuids"]),
            topology_digest=nccl_payload["topology_digest"],
        )
    def telemetry(item: dict) -> GpuTelemetryObservation:
        raw = item.get("telemetry")
        if raw is None:
            return GpuTelemetryObservation.unavailable()
        fields = {}
        for name, value in raw.items():
            if name == "collector_identity":
                continue
            fields[name] = TelemetryEvidence(
                status=TelemetryStatus(value["status"]),
                value=value.get("value"),
                source=value["source"],
                collected_at=int(value.get("collected_at", 0)),
                error=value.get("error"),
            )
        return GpuTelemetryObservation(**fields, collector_identity=raw["collector_identity"])

    return GpuHostObservation(
        worker_id=payload["worker_id"],
        driver_version=payload["driver_version"],
        cuda_supported_version=payload["cuda_supported_version"],
        gpus=tuple(
            GpuDeviceObservation(
                index=int(item["index"]),
                uuid=item["uuid"],
                name=item["name"],
                memory_total_mib=int(item["memory_total_mib"]),
                memory_used_mib=int(item["memory_used_mib"]),
                pci_bus_id=item["pci_bus_id"],
                compute_capability=item["compute_capability"],
                telemetry=telemetry(item),
            )
            for item in payload["gpus"]
        ),
        topology_text=payload.get("topology_text"),
        dcgm_available=payload["dcgm_available"],
        dcgm_version=payload.get("dcgm_version"),
        health_json=payload.get("health_json"),
        nccl_evidence=nccl_evidence,
        topology_evidence=topology_evidence,
        observed_at=int(payload.get("observed_at", 0)),
        collector_identity=payload.get("collector_identity", "legacy_observation"),
    )


class SQLiteWorkerRegistryStore:
    """Small standard-library persistence layer for worker observations."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def save(self, registry: WorkerRegistry) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM workers")
            for record in registry.snapshot():
                payload = asdict(record)
                payload["state"] = record.state.value
                payload["resource"]["gpu_models"] = list(record.resource.gpu_models)
                payload["resource"]["capabilities"] = list(record.resource.capabilities)
                payload["resource"]["installed_engines"] = list(record.resource.installed_engines)
                payload["hardware_observation"] = _serialize_observation(record.hardware_observation)
        payload["gpu_capabilities"] = _serialize_capabilities(record.gpu_capabilities)
                connection.execute("INSERT INTO workers VALUES (?, ?)", (record.id, json.dumps(payload, sort_keys=True)))

    def load(self) -> WorkerRegistry:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT payload FROM workers ORDER BY id").fetchall()
        records: list[WorkerRecord] = []
        for (payload_json,) in rows:
            payload = json.loads(payload_json)
            resource_payload = payload.pop("resource")
            resource_payload["gpu_models"] = tuple(resource_payload["gpu_models"])
            resource_payload["capabilities"] = tuple(resource_payload["capabilities"])
            resource_payload["installed_engines"] = tuple(resource_payload["installed_engines"])
            resource = ComputeResource(**resource_payload)
            payload["state"] = WorkerState(payload["state"])
            payload["hardware_observation"] = _deserialize_observation(payload.get("hardware_observation"))
            payload["gpu_capabilities"] = _deserialize_capabilities(payload.get("gpu_capabilities"))
            records.append(WorkerRecord(resource=resource, **payload))
        return WorkerRegistry(tuple(records))
