"""Durable registry for observed heterogeneous compute workers."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from .gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
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


def _serialize_observation(observation: GpuHostObservation | None) -> dict | None:
    return None if observation is None else asdict(observation)


def _deserialize_observation(payload: dict | None) -> GpuHostObservation | None:
    if payload is None:
        return None
    return GpuHostObservation(
        worker_id=payload["worker_id"],
        driver_version=payload["driver_version"],
        cuda_supported_version=payload["cuda_supported_version"],
        gpus=tuple(GpuDeviceObservation(**item) for item in payload["gpus"]),
        topology_text=payload.get("topology_text"),
        dcgm_available=payload["dcgm_available"],
        dcgm_version=payload.get("dcgm_version"),
        health_json=payload.get("health_json"),
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
            records.append(WorkerRecord(resource=resource, **payload))
        return WorkerRegistry(tuple(records))
