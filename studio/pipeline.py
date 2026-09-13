"""Checkpointed stage execution with durable resume support."""

from dataclasses import dataclass, field
from typing import Callable, Any, Protocol

STAGES = (
    "interpret",
    "plan_episode",
    "build_scenes",
    "build_shots",
    "resolve_assets",
    "animate",
    "dialogue",
    "lip_sync",
    "sound_music",
    "composite",
    "edit",
    "qc",
    "story_fidelity",
    "approval",
    "master",
    "archive",
)


@dataclass
class RunState:
    episode_id: str
    completed: set[str] = field(default_factory=set)
    outputs: dict[str, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)


class CheckpointWriter(Protocol):
    def save(self, state: RunState) -> object:
        ...


class Pipeline:
    def __init__(self, state: RunState, checkpoint: CheckpointWriter | None = None):
        self.state = state
        self.checkpoint = checkpoint

    def run(self, handlers: dict[str, Callable[[RunState], Any]]) -> RunState:
        for stage in STAGES:
            if stage in self.state.completed:
                continue
            handler = handlers.get(stage)
            if handler is None:
                raise RuntimeError(f"No handler registered for required stage: {stage}")
            try:
                result = handler(self.state)
                if result is not None:
                    self.state.outputs[stage] = str(result)
                self.state.completed.add(stage)
                self.state.failures.pop(stage, None)
                if self.checkpoint is not None:
                    self.checkpoint.save(self.state)
            except Exception as exc:
                self.state.failures[stage] = f"{type(exc).__name__}: {exc}"
                if self.checkpoint is not None:
                    self.checkpoint.save(self.state)
                raise
        return self.state
