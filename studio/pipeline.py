"""Checkpointed stage execution.

The executor tracks completed stages and treats failed work as retryable. A real
render adapter can later implement the stage callable without changing this state
machine.
"""

from dataclasses import dataclass, field
from typing import Callable, Any

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


class Pipeline:
    def __init__(self, state: RunState):
        self.state = state

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
            except Exception as exc:
                self.state.failures[stage] = f"{type(exc).__name__}: {exc}"
                raise
        return self.state
