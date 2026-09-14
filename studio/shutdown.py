"""Checkpoint-safe worker draining and recovery coordination."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WorkerDrainState(StrEnum):
    RUNNING = "running"
    DRAINING = "draining"
    DRAINED = "drained"


@dataclass(frozen=True)
class ShutdownDecision:
    state: WorkerDrainState
    finish_current_job: bool
    start_new_jobs: bool
    reason: str


class ShutdownCoordinator:
    """Coordinate safe local shutdown without pretending to control physical power."""

    def __init__(self) -> None:
        self._state = WorkerDrainState.RUNNING

    @property
    def state(self) -> WorkerDrainState:
        return self._state

    def request_drain(self, reason: str = "operator requested drain") -> ShutdownDecision:
        if not reason.strip():
            raise ValueError("drain reason is required")
        self._state = WorkerDrainState.DRAINING
        return ShutdownDecision(self._state, True, False, reason)

    def checkpoint_completed(self) -> ShutdownDecision:
        if self._state != WorkerDrainState.DRAINING:
            raise RuntimeError("worker is not draining")
        self._state = WorkerDrainState.DRAINED
        return ShutdownDecision(self._state, False, False, "checkpoint boundary reached")

    def recovery_after_restart(self) -> ShutdownDecision:
        self._state = WorkerDrainState.RUNNING
        return ShutdownDecision(self._state, False, True, "worker restarted; durable leases may be recovered")
