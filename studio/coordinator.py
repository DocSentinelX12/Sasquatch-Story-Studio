"""Durable coordinator boundary between episode pipelines and the shared worker scheduler."""
from __future__ import annotations

from dataclasses import dataclass

from .pipeline import STAGES
from .resources import ComputeResource, ResourceSnapshot
from .scheduler import Job, JobRequirements, Scheduler


@dataclass(frozen=True)
class StageJob:
    """Stable production identity carried by a scheduler job."""

    episode_id: str
    stage: str
    job_id: str


class ProductionCoordinator:
    """Turn canonical episode stages into schedulable, recoverable local work."""

    def __init__(self, scheduler: Scheduler):
        self.scheduler = scheduler
        self._stage_jobs: dict[str, StageJob] = {}
        for job in scheduler.snapshot():
            episode_id, separator, stage = job.id.partition(":")
            if separator and stage in STAGES:
                self._stage_jobs[job.id] = StageJob(episode_id, stage, job.id)

    @staticmethod
    def _job_id(episode_id: str, stage: str) -> str:
        if not episode_id.strip():
            raise ValueError("episode_id is required")
        if stage not in STAGES:
            raise ValueError(f"unknown production stage: {stage}")
        return f"{episode_id}:{stage}"

    def submit_stage(self, episode_id: str, stage: str, requirements: JobRequirements, priority: int = 0) -> Job:
        job_id = self._job_id(episode_id, stage)
        job = Job(id=job_id, requirements=requirements, priority=priority)
        self.scheduler.submit(job)
        self._stage_jobs[job_id] = StageJob(episode_id, stage, job_id)
        return job

    def lease(
        self,
        worker_id: str,
        worker_resource: ComputeResource,
        resources: ResourceSnapshot,
        now: int,
        lease_seconds: int = 900,
    ) -> Job:
        job = self.scheduler.choose(worker_id, resources, now, lease_seconds)
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
        return stage_job

    def recover(self, now: int) -> tuple[str, ...]:
        return self.scheduler.recover_expired(now)

    def stage_for(self, job_id: str) -> StageJob:
        try:
            return self._stage_jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"unknown production stage job: {job_id}") from exc
