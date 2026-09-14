"""Worker-neutral task lifecycle contracts with durable identity."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .scheduler import Scheduler


class WorkerResultState(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"


@dataclass(frozen=True)
class WorkerTask:
    task_id: str
    episode_id: str
    stage: str
    shot_id: str
    input_refs: tuple[str, ...]
    input_hashes: tuple[str, ...]
    requirements: object
    provenance_context: tuple[tuple[str, str], ...] = ()
    canonical_source_hash: str = ""
    payload_json: str = ""

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id is required")
        if len(self.input_refs) != len(self.input_hashes):
            raise ValueError("input references and hashes must have equal lengths")
        if self.canonical_source_hash and (len(self.canonical_source_hash) != 64 or any(c not in "0123456789abcdef" for c in self.canonical_source_hash.lower())):
            raise ValueError("canonical_source_hash must be a SHA-256 hex digest")


@dataclass(frozen=True)
class WorkerResult:
    task_id: str
    state: WorkerResultState
    output_refs: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class WorkerHeartbeat:
    worker_id: str
    observed_at: int


@dataclass(frozen=True)
class WorkerFailure:
    worker_id: str
    task_id: str
    reason: str


class WorkerExecutor(Protocol):
    def execute(self, task: WorkerTask) -> WorkerResult:
        ...


class WorkerCoordinator:
    """Thin lifecycle facade over the existing scheduler lease authority."""

    def __init__(self, scheduler: Scheduler):
        self.scheduler = scheduler

    def complete(self, task_id: str, worker_id: str) -> None:
        self.scheduler.complete(task_id, worker_id)

    def recover(self, now: int) -> tuple[str, ...]:
        return self.scheduler.recover_expired(now)
