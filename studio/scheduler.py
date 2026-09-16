"""Deterministic scheduler core and durable local persistence."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Iterable
from pathlib import Path

from .hardware_requirements import HardwareRequirements
from .resources import ComputeResource, ResourceSnapshot


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
    hardware: HardwareRequirements | None = None

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
    allocated_gpu_uuids: tuple[str, ...] = ()


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
        reserved = tuple(job.requirements for job in self._jobs.values() if job.state == JobState.LEASED)
        for job in candidates:
            if not _fits(job.requirements, resources, reserved):
                continue
            leased = Job(job.id, job.requirements, job.priority, JobState.LEASED, worker_id, now + lease_seconds)
            self._jobs[job.id] = leased
            return leased
        return None

    def choose_on_worker(
        self,
        worker_id: str,
        worker_resource: ComputeResource,
        pool_power_watts: int,
        now: int,
        lease_seconds: int = 900,
        job_id: str | None = None,
        gpu_uuids: tuple[str, ...] = (),
    ) -> Job | None:
        """Lease work for this worker and bind any verified GPU allocation to it."""
        if not worker_id.strip() or lease_seconds < 1 or pool_power_watts < 0:
            raise ValueError("worker_id, lease duration, and power must be valid")
        if job_id is not None and not job_id.strip():
            raise ValueError("job_id cannot be empty")
        if len(set(gpu_uuids)) != len(gpu_uuids) or any(not uuid.strip() for uuid in gpu_uuids):
            raise ValueError("GPU allocation must contain unique non-empty UUIDs")
        if not worker_resource.healthy:
            return None
        candidates = sorted(
            (
                j
                for j in self._jobs.values()
                if j.state == JobState.QUEUED and (job_id is None or j.id == job_id)
            ),
            key=lambda j: (-j.priority, j.id),
        )
        leased_jobs = tuple(job for job in self._jobs.values() if job.state == JobState.LEASED)
        reserved_pool_power = sum(job.requirements.power_watts for job in leased_jobs)
        reserved_on_worker = tuple(job.requirements for job in leased_jobs if job.lease_owner == worker_id)
        reserved_gpu_uuids = {
            uuid
            for job in leased_jobs
            if job.lease_owner == worker_id
            for uuid in job.allocated_gpu_uuids
        }
        if reserved_gpu_uuids.intersection(gpu_uuids):
            return None
        worker_snapshot = ResourceSnapshot(compute=(worker_resource,), power=())
        for job in candidates:
            if pool_power_watts - reserved_pool_power < job.requirements.power_watts:
                continue
            if not _fits(job.requirements, worker_snapshot, reserved=reserved_on_worker, check_power=False):
                continue
            leased = Job(job.id, job.requirements, job.priority, JobState.LEASED, worker_id, now + lease_seconds, gpu_uuids)
            self._jobs[job.id] = leased
            return leased
        return None

    def complete(self, job_id: str, worker_id: str) -> None:
        job = self._jobs[job_id]
        if job.state != JobState.LEASED or job.lease_owner != worker_id:
            raise RuntimeError("only the current lease owner can complete a job")
        self._jobs[job.id] = Job(job.id, job.requirements, job.priority, JobState.COMPLETED)

    def requeue(self, job_id: str, worker_id: str) -> None:
        job = self._jobs[job_id]
        if job.state != JobState.LEASED or job.lease_owner != worker_id:
            raise RuntimeError("only the current lease owner can requeue a job")
        self._jobs[job.id] = Job(job.id, job.requirements, job.priority, JobState.QUEUED)

    def fail(self, job_id: str, worker_id: str) -> None:
        job = self._jobs[job_id]
        if job.state != JobState.LEASED or job.lease_owner != worker_id:
            raise RuntimeError("only the current lease owner can fail a job")
        self._jobs[job.id] = Job(job.id, job.requirements, job.priority, JobState.FAILED)

    def snapshot(self) -> tuple[Job, ...]:
        return tuple(self._jobs[key] for key in sorted(self._jobs))


def _fits(req: JobRequirements, resources: ResourceSnapshot, reserved: Iterable[JobRequirements] = (), check_power: bool = True) -> bool:
    healthy = [r for r in resources.compute if r.healthy]
    reserved_requirements = tuple(reserved)
    reserved_slots = sum(item.slots for item in reserved_requirements)
    reserved_memory = sum(item.memory_bytes for item in reserved_requirements)
    reserved_vram = sum(item.vram_bytes for item in reserved_requirements)
    reserved_scratch = sum(item.scratch_bytes for item in reserved_requirements)
    reserved_power = sum(item.power_watts for item in reserved_requirements)
    if sum(r.logical_slots for r in healthy) - reserved_slots < req.slots:
        return False
    if req.memory_bytes and (sum(r.memory_bytes for r in healthy) - reserved_memory < req.memory_bytes or max((r.memory_bytes for r in healthy), default=0) < req.memory_bytes):
        return False
    if req.vram_bytes and (sum(r.vram_bytes for r in healthy) - reserved_vram < req.vram_bytes or max((r.vram_bytes for r in healthy), default=0) < req.vram_bytes):
        return False
    if req.scratch_bytes and (sum(r.scratch_bytes for r in healthy) - reserved_scratch < req.scratch_bytes or max((r.scratch_bytes for r in healthy), default=0) < req.scratch_bytes):
        return False
    if check_power and req.power_watts and resources.healthy_power_watts - reserved_power < req.power_watts:
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
            connection.execute("CREATE TABLE IF NOT EXISTS scheduler_jobs (id TEXT PRIMARY KEY, requirements_json TEXT NOT NULL, priority INTEGER NOT NULL, state TEXT NOT NULL, lease_owner TEXT, lease_until INTEGER, allocated_gpu_uuids_json TEXT NOT NULL DEFAULT '[]')")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(scheduler_jobs)")}
            if "allocated_gpu_uuids_json" not in columns:
                connection.execute("ALTER TABLE scheduler_jobs ADD COLUMN allocated_gpu_uuids_json TEXT NOT NULL DEFAULT '[]'")

    def save(self, scheduler: Scheduler) -> None:
        rows = []
        for job in scheduler.snapshot():
            hardware = None
            if job.requirements.hardware is not None:
                item = job.requirements.hardware
                hardware = {
                    "min_gpu_count": item.min_gpu_count,
                    "min_vram_per_gpu_bytes": item.min_vram_per_gpu_bytes,
                    "min_total_vram_bytes": item.min_total_vram_bytes,
                    "min_compute_capability": item.min_compute_capability,
                    "required_gpu_models": list(item.required_gpu_models),
                    "placement": item.placement.value,
                    "require_nccl": item.require_nccl,
                    "allow_multi_node": item.allow_multi_node,
                    "require_gpu_direct_network": item.require_gpu_direct_network,
                }
            }
            rows.append((job.id, json.dumps({"slots": job.requirements.slots, "memory_bytes": job.requirements.memory_bytes, "vram_bytes": job.requirements.vram_bytes, "scratch_bytes": job.requirements.scratch_bytes, "power_watts": job.requirements.power_watts, "capabilities": job.requirements.capabilities, "engines": job.requirements.engines, "hardware": hardware}, sort_keys=True), job.priority, job.state.value, job.lease_owner, job.lease_until, json.dumps(job.allocated_gpu_uuids)))
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM scheduler_jobs")
            connection.executemany("INSERT INTO scheduler_jobs (id, requirements_json, priority, state, lease_owner, lease_until, allocated_gpu_uuids_json) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)

    def load(self) -> Scheduler:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT id, requirements_json, priority, state, lease_owner, lease_until, allocated_gpu_uuids_json FROM scheduler_jobs ORDER BY id").fetchall()
        jobs = []
        for job_id, requirements_json, priority, state, lease_owner, lease_until, allocated_gpu_uuids_json in rows:
            data = json.loads(requirements_json)
            hardware_data = data.get("hardware")
            hardware = None
            if hardware_data is not None:
                from .hardware_requirements import GpuPlacement
                hardware = HardwareRequirements(
                    min_gpu_count=hardware_data["min_gpu_count"],
                    min_vram_per_gpu_bytes=hardware_data["min_vram_per_gpu_bytes"],
                    min_total_vram_bytes=hardware_data["min_total_vram_bytes"],
                    min_compute_capability=hardware_data["min_compute_capability"],
                    required_gpu_models=tuple(hardware_data["required_gpu_models"]),
                    placement=GpuPlacement(hardware_data["placement"]),
                    require_nccl=hardware_data["require_nccl"],
                    allow_multi_node=hardware_data["allow_multi_node"],
                    require_gpu_direct_network=hardware_data["require_gpu_direct_network"],
                )
            requirements = JobRequirements(slots=data["slots"], memory_bytes=data["memory_bytes"], vram_bytes=data["vram_bytes"], scratch_bytes=data["scratch_bytes"], power_watts=data["power_watts"], capabilities=tuple(data["capabilities"]), engines=tuple(data["engines"]), hardware=hardware)
            jobs.append(Job(job_id, requirements, priority, JobState(state), lease_owner, lease_until, tuple(json.loads(allocated_gpu_uuids_json))))
        return Scheduler(jobs)
