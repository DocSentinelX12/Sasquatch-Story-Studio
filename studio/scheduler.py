"""Deterministic scheduler core and durable local persistence."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from .resources import ResourceSnapshot


class JobState(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass(frozen=True)
class JobRequirements:
    slots: int = 1
    memory_bytes: int = 0
    vram_bytes: int = 0
    scratch_bytes: int = 0
    power_watts: int = 0
    capabilities: tuple[str, ...] = ()
    engines: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.slots < 1:
            raise ValueError("jobs require at least one logical slot")
        for name, value in (("memory_bytes", self.memory_bytes), ("vram_bytes", self.vram_bytes), ("scratch_bytes", self.scratch_bytes), ("power_watts", self.power_watts)):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True)
class Job:
    id: str
    requirements: JobRequirements
    priority: int = 0
    state: JobState = JobState.QUEUED
    lease_owner: str | None = None
    lease_until: int | None = None


class Scheduler:
    """Select work from a shared pool using observed resource capacity."""

    def __init__(self, jobs: Iterable[Job] = ()):
        self._jobs = {job.id: job for job in jobs}

    def submit(self, job: Job) -> None:
        if not job.id.strip():
            raise ValueError("job id is required")
        if job.id in self._jobs:
            raise ValueError(f"job already exists: {job.id}")
        self._jobs[job.id] = job

    def recover_expired(self, now: int) -> tuple[str, ...]:
        recovered: list[str] = []
        for job in list(self._jobs.values()):
            if job.state == JobState.LEASED and job.lease_until is not None and job.lease_until <= now:
                self._jobs[job.id] = Job(job.id, job.requirements, job.priority, JobState.QUEUED)
                recovered.append(job.id)
        return tuple(sorted(recovered))

    def choose(self, worker_id: str, resources: ResourceSnapshot, now: int, lease_seconds: int = 900) -> Job | None:
        if not worker_id.strip() or lease_seconds < 1:
            raise ValueError("worker_id and positive lease duration are required")
        candidates = sorted((j for j in self._jobs.values() if j.state == JobState.QUEUED), key=lambda j: (-j.priority, j.id))
        for job in candidates:
            if not _fits(job.requirements, resources):
                continue
            leased = Job(job.id, job.requirements, job.priority, JobState.LEASED, worker_id, now + lease_seconds)
            self._jobs[job.id] = leased
            return leased
        return None

    def complete(self, job_id: str, worker_id: str) -> None:
        job = self._jobs[job_id]
        if job.state != JobState.LEASED or job.lease_owner != worker_id:
            raise RuntimeError("only the current lease owner can complete a job")
        self._jobs[job_id] = Job(job.id, job.requirements, job.priority, JobState.COMPLETED)

    def snapshot(self) -> tuple[Job, ...]:
        return tuple(self._jobs[key] for key in sorted(self._jobs))


def _fits(req: JobRequirements, resources: ResourceSnapshot) -> bool:
    healthy = [r for r in resources.compute if r.healthy]
    if sum(r.logical_slots for r in healthy) < req.slots:
        return False
    if req.memory_bytes and max((r.memory_bytes for r in healthy), default=0) < req.memory_bytes:
        return False
    if req.vram_bytes and max((r.vram_bytes for r in healthy), default=0) < req.vram_bytes:
        return False
    if req.scratch_bytes and max((r.scratch_bytes for r in healthy), default=0) < req.scratch_bytes:
        return False
    if req.power_watts and resources.healthy_power_watts < req.power_watts:
        return False
    available_caps = {cap for resource in healthy for cap in resource.capabilities}
    available_engines = {engine for resource in healthy for engine in resource.installed_engines}
    return set(req.capabilities).issubset(available_caps) and set(req.engines).issubset(available_engines)


class SQLiteSchedulerStore:
    """Durable scheduler state using only Python's local SQLite library."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS scheduler_jobs ("
                "id TEXT PRIMARY KEY, requirements_json TEXT NOT NULL, priority INTEGER NOT NULL, "
                "state TEXT NOT NULL, lease_owner TEXT, lease_until INTEGER)"
            )

    def save(self, scheduler: Scheduler) -> None:
        rows = []
        for job in scheduler.snapshot():
            rows.append((
                job.id,
                json.dumps({
                    "slots": job.requirements.slots,
                    "memory_bytes": job.requirements.memory_bytes,
                    "vram_bytes": job.requirements.vram_bytes,
                    "scratch_bytes": job.requirements.scratch_bytes,
                    "power_watts": job.requirements.power_watts,
                    "capabilities": job.requirements.capabilities,
                    "engines": job.requirements.engines,
                }, sort_keys=True),
                job.priority,
                job.state.value,
                job.lease_owner,
                job.lease_until,
            ))
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM scheduler_jobs")
            connection.executemany("INSERT INTO scheduler_jobs VALUES (?, ?, ?, ?, ?, ?)", rows)

    def load(self) -> Scheduler:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT id, requirements_json, priority, state, lease_owner, lease_until "
                "FROM scheduler_jobs ORDER BY id"
            ).fetchall()
        jobs = []
        for job_id, requirements_json, priority, state, lease_owner, lease_until in rows:
            data = json.loads(requirements_json)
            requirements = JobRequirements(
                slots=data["slots"], memory_bytes=data["memory_bytes"], vram_bytes=data["vram_bytes"],
                scratch_bytes=data["scratch_bytes"], power_watts=data["power_watts"],
                capabilities=tuple(data["capabilities"]), engines=tuple(data["engines"]),
            )
            jobs.append(Job(job_id, requirements, priority, JobState(state), lease_owner, lease_until))
        return Scheduler(jobs)
