"""Observed worker registry for horizontally scalable local production."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .resources import ComputeResource


@dataclass(frozen=True)
class WorkerHeartbeat:
    worker_id: str
    observed_at: int
    healthy: bool = True
    active_job_ids: tuple[str, ...] = ()
    thermal_celsius: float | None = None
    utilization_percent: float | None = None

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("worker id is required")
        if self.observed_at < 0:
            raise ValueError("heartbeat timestamp cannot be negative")
        if self.thermal_celsius is not None and self.thermal_celsius < -50:
            raise ValueError("invalid thermal_celsius")
        if self.utilization_percent is not None and not 0 <= self.utilization_percent <= 100:
            raise ValueError("invalid utilization_percent")


@dataclass(frozen=True)
class Worker:
    id: str
    resource: ComputeResource
    heartbeat: WorkerHeartbeat

    def __post_init__(self) -> None:
        if not self.id.strip() or self.id != self.heartbeat.worker_id:
            raise ValueError("worker id must match heartbeat")


class WorkerRegistry:
    """In-memory registry of observed workers; durable storage is layered above it."""

    def __init__(self, workers: Iterable[Worker] = ()):
        self._workers = {worker.id: worker for worker in workers}

    def register(self, worker: Worker) -> None:
        self._workers[worker.id] = worker

    def heartbeat(self, heartbeat: WorkerHeartbeat) -> None:
        worker = self._workers.get(heartbeat.worker_id)
        if worker is None:
            raise KeyError(f"unknown worker: {heartbeat.worker_id}")
        if heartbeat.observed_at < worker.heartbeat.observed_at:
            raise ValueError("worker heartbeat timestamp moved backwards")
        self._workers[worker.id] = Worker(worker.id, worker.resource, heartbeat)

    def get(self, worker_id: str) -> Worker:
        try:
            return self._workers[worker_id]
        except KeyError as exc:
            raise KeyError(f"unknown worker: {worker_id}") from exc

    def remove(self, worker_id: str) -> None:
        self._workers.pop(worker_id, None)

    def snapshot(self) -> tuple[Worker, ...]:
        return tuple(self._workers[key] for key in sorted(self._workers))

    def stale_worker_ids(self, now: int, max_age_seconds: int) -> tuple[str, ...]:
        if now < 0 or max_age_seconds < 1:
            raise ValueError("now must be nonnegative and max_age_seconds must be positive")
        return tuple(
            worker.id
            for worker in self.snapshot()
            if now - worker.heartbeat.observed_at > max_age_seconds
        )

    def healthy_resources(self, now: int | None = None, max_age_seconds: int | None = None) -> tuple[ComputeResource, ...]:
        if (now is None) != (max_age_seconds is None):
            raise ValueError("now and max_age_seconds must be supplied together")
        if now is not None and max_age_seconds is not None:
            if now < 0 or max_age_seconds < 1:
                raise ValueError("now must be nonnegative and max_age_seconds must be positive")
        return tuple(
            worker.resource
            for worker in self._workers.values()
            if worker.heartbeat.healthy
            and worker.resource.healthy
            and (now is None or now - worker.heartbeat.observed_at <= max_age_seconds)
        )


class SQLiteWorkerStore:
    """Durable local worker observations using only Python's SQLite library."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS workers ("
                "id TEXT PRIMARY KEY, resource_json TEXT NOT NULL, heartbeat_json TEXT NOT NULL)"
            )

    def save(self, registry: WorkerRegistry) -> None:
        rows = []
        for worker in registry.snapshot():
            resource = worker.resource
            heartbeat = worker.heartbeat
            rows.append((
                worker.id,
                json.dumps({
                    "id": resource.id,
                    "cpu_cores": resource.cpu_cores,
                    "memory_bytes": resource.memory_bytes,
                    "gpu_count": resource.gpu_count,
                    "gpu_models": resource.gpu_models,
                    "vram_bytes": resource.vram_bytes,
                    "capabilities": resource.capabilities,
                    "installed_engines": resource.installed_engines,
                    "logical_slots": resource.logical_slots,
                    "healthy": resource.healthy,
                    "power_budget_watts": resource.power_budget_watts,
                    "scratch_bytes": resource.scratch_bytes,
                }, sort_keys=True),
                json.dumps({
                    "worker_id": heartbeat.worker_id,
                    "observed_at": heartbeat.observed_at,
                    "healthy": heartbeat.healthy,
                    "active_job_ids": heartbeat.active_job_ids,
                    "thermal_celsius": heartbeat.thermal_celsius,
                    "utilization_percent": heartbeat.utilization_percent,
                }, sort_keys=True),
            ))
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM workers")
            connection.executemany("INSERT INTO workers VALUES (?, ?, ?)", rows)

    def load(self) -> WorkerRegistry:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT id, resource_json, heartbeat_json FROM workers ORDER BY id"
            ).fetchall()
        workers = []
        for worker_id, resource_json, heartbeat_json in rows:
            resource_data = json.loads(resource_json)
            heartbeat_data = json.loads(heartbeat_json)
            resource = ComputeResource(
                id=resource_data["id"],
                cpu_cores=resource_data["cpu_cores"],
                memory_bytes=resource_data["memory_bytes"],
                gpu_count=resource_data["gpu_count"],
                gpu_models=tuple(resource_data["gpu_models"]),
                vram_bytes=resource_data["vram_bytes"],
                capabilities=tuple(resource_data["capabilities"]),
                installed_engines=tuple(resource_data["installed_engines"]),
                logical_slots=resource_data["logical_slots"],
                healthy=resource_data["healthy"],
                power_budget_watts=resource_data["power_budget_watts"],
                scratch_bytes=resource_data["scratch_bytes"],
            )
            heartbeat = WorkerHeartbeat(
                worker_id=heartbeat_data["worker_id"],
                observed_at=heartbeat_data["observed_at"],
                healthy=heartbeat_data["healthy"],
                active_job_ids=tuple(heartbeat_data["active_job_ids"]),
                thermal_celsius=heartbeat_data["thermal_celsius"],
                utilization_percent=heartbeat_data["utilization_percent"],
            )
            if worker_id != heartbeat.worker_id:
                raise ValueError("persisted worker identity mismatch")
            workers.append(Worker(worker_id, resource, heartbeat))
        return WorkerRegistry(workers)
