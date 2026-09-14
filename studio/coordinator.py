"""Durable coordinator boundary between episode pipelines and the shared worker scheduler."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .pipeline import STAGES
from .resources import ComputeResource, ResourceSnapshot
from .scheduler import Job, JobRequirements, Scheduler


@dataclass(frozen=True)
class StageJob:
    """Stable production identity and durable handoff metadata for a scheduler job."""

    episode_id: str
    stage: str
    job_id: str
    canonical_source_hash: str = ""
    output_ref: str = ""


class CoordinatorStore:
    """Durable local SQLite storage for stage handoff metadata."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS coordinator_stage_jobs ("
                "job_id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, stage TEXT NOT NULL, "
                "canonical_source_hash TEXT NOT NULL, output_ref TEXT NOT NULL)"
            )

    def save(self, stage_job: StageJob) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO coordinator_stage_jobs "
                "(job_id, episode_id, stage, canonical_source_hash, output_ref) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET "
                "episode_id=excluded.episode_id, stage=excluded.stage, "
                "canonical_source_hash=excluded.canonical_source_hash, output_ref=excluded.output_ref",
                (
                    stage_job.job_id,
                    stage_job.episode_id,
                    stage_job.stage,
                    stage_job.canonical_source_hash,
                    stage_job.output_ref,
                ),
            )

    def load(self) -> tuple[StageJob, ...]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT episode_id, stage, job_id, canonical_source_hash, output_ref "
                "FROM coordinator_stage_jobs ORDER BY job_id"
            ).fetchall()
        return tuple(StageJob(*row) for row in rows)


class ProductionCoordinator:
    """Turn canonical episode stages into schedulable, recoverable local work."""

    def __init__(self, scheduler: Scheduler, store: CoordinatorStore | None = None):
        self.scheduler = scheduler
        self.store = store
        self._stage_jobs: dict[str, StageJob] = {}
        for job in scheduler.snapshot():
            episode_id, separator, stage = job.id.partition(":")
            if separator and stage in STAGES:
                self._stage_jobs[job.id] = StageJob(episode_id, stage, job.id)
        if store is not None:
            for stage_job in store.load():
                if stage_job.job_id in self._stage_jobs:
                    self._stage_jobs[stage_job.job_id] = stage_job

    @staticmethod
    def _job_id(episode_id: str, stage: str) -> str:
        if not episode_id.strip():
            raise ValueError("episode_id is required")
        if stage not in STAGES:
            raise ValueError(f"unknown production stage: {stage}")
        return f"{episode_id}:{stage}"

    @staticmethod
    def _validate_hash(canonical_source_hash: str) -> None:
        if not canonical_source_hash:
            return
        if len(canonical_source_hash) != 64:
            raise ValueError("canonical_source_hash must be a SHA-256 hex digest")
        try:
            int(canonical_source_hash, 16)
        except ValueError as exc:
            raise ValueError("canonical_source_hash must be a SHA-256 hex digest") from exc

    def submit_stage(
        self,
        episode_id: str,
        stage: str,
        requirements: JobRequirements,
        priority: int = 0,
        canonical_source_hash: str = "",
    ) -> Job:
        self._validate_hash(canonical_source_hash)
        job_id = self._job_id(episode_id, stage)
        job = Job(id=job_id, requirements=requirements, priority=priority)
        self.scheduler.submit(job)
        stage_job = StageJob(episode_id, stage, job_id, canonical_source_hash)
        self._stage_jobs[job_id] = stage_job
        if self.store is not None:
            self.store.save(stage_job)
        return job

    def lease(
        self,
        worker_id: str,
        worker_resource: ComputeResource,
        resources: ResourceSnapshot,
        now: int,
        lease_seconds: int = 900,
    ) -> Job:
        """Lease work against this worker's observed compute capacity and pool power."""
        job = self.scheduler.choose_on_worker(
            worker_id,
            worker_resource,
            resources.healthy_power_watts,
            now,
            lease_seconds,
        )
        if job is None:
            raise RuntimeError("no schedulable production stage is available for this worker")
        return job

    def complete(self, job_id: str, worker_id: str, output_ref: str) -> StageJob:
        if not output_ref.strip():
            raise ValueError("output_ref is required")
        stage_job = self._stage_jobs.get(job_id)
        if stage_job is None:
            raise KeyError(f"unknown production stage job: {job_id}")
        self.scheduler.complete(job_id, worker_id)
        completed = StageJob(
            stage_job.episode_id,
            stage_job.stage,
            stage_job.job_id,
            stage_job.canonical_source_hash,
            output_ref,
        )
        self._stage_jobs[job_id] = completed
        if self.store is not None:
            self.store.save(completed)
        return completed

    def recover(self, now: int) -> tuple[str, ...]:
        return self.scheduler.recover_expired(now)

    def stage_for(self, job_id: str) -> StageJob:
        try:
            return self._stage_jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"unknown production stage job: {job_id}") from exc
