"""Episode-level orchestration boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .checkpoints import CheckpointStore
from .pipeline import Pipeline, RunState, STAGES


@dataclass(frozen=True)
class EpisodeRun:
    episode_id: str
    completed_stages: tuple[str, ...]
    outputs: dict[str, str]
    failures: dict[str, str]


def run_episode(episode_id: str, handlers: dict[str, Callable[[RunState], Any]], checkpoint_dir: str) -> EpisodeRun:
    """Resume an episode from its durable checkpoint and execute only unfinished stages."""
    store = CheckpointStore(checkpoint_dir)
    state = store.load(episode_id)
    final = Pipeline(state, checkpoint=store).run(handlers)
    return EpisodeRun(
        episode_id=episode_id,
        completed_stages=tuple(stage for stage in STAGES if stage in final.completed),
        outputs=dict(final.outputs),
        failures=dict(final.failures),
    )
