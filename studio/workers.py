"""Observed worker registry for horizontally scalable local production."""
from __future__ import annotations

from dataclasses import dataclass
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
        for name, value in (("thermal_celsius", self.thermal_celsius), ("utilization_percent", self.utilization_percent)):
            if value is not None and not 0 <= value <= 100 if name == "utilization_percent" else value is not None and value < -50:
                raise ValueError(f"invalid {name}")


@dataclass(frozen=True)
class Worker:
    id: str
    resource: ComputeResource
    heartbeat: WorkerHeartbeat

    def __post_init__(self) -> None:
        if self.id.strip() == "" or self.id != self.heartbeat.worker_id:
            raise ValueError("worker id must match heartbeat")
        if self.resource.id.strip() == "":
            raise ValueError("worker resource id is required")


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
        self._workers[worker.id] = Worker(worker.id, worker.resource, heartbeat)

    def remove(self, worker_id: str) -> None:
        self._workers.pop(worker_id, None)

    def snapshot(self) -> tuple[Worker, ...]:
        return tuple(self._workers[key] for key in sorted(self._workers))

    def healthy_resources(self) -> tuple[ComputeResource, ...]:
        return tuple(worker.resource for worker in self._workers.values() if worker.heartbeat.healthy and worker.resource.healthy)
