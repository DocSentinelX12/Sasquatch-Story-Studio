"""Durable JSON checkpoints for resumable episode production."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from .pipeline import RunState, STAGES


class CheckpointStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, episode_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in episode_id)
        if not safe:
            raise ValueError("episode_id must contain at least one safe character")
        return self.root / f"{safe}.json"

    def save(self, state: RunState) -> Path:
        unknown = state.completed.difference(STAGES)
        if unknown:
            raise ValueError(f"checkpoint contains unknown stages: {sorted(unknown)}")
        destination = self.path_for(state.episode_id)
        payload = {
            "episode_id": state.episode_id,
            "completed": sorted(state.completed, key=STAGES.index),
            "outputs": dict(sorted(state.outputs.items())),
            "failures": dict(sorted(state.failures.items())),
        }
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(destination)
        return destination

    def load(self, episode_id: str) -> RunState:
        source = self.path_for(episode_id)
        if not source.exists():
            return RunState(episode_id=episode_id)
        payload: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
        if payload.get("episode_id") != episode_id:
            raise ValueError("checkpoint episode_id does not match requested episode")
        completed = set(payload.get("completed", []))
        unknown = completed.difference(STAGES)
        if unknown:
            raise ValueError(f"checkpoint contains unknown stages: {sorted(unknown)}")
        return RunState(
            episode_id=episode_id,
            completed=completed,
            outputs=dict(payload.get("outputs", {})),
            failures=dict(payload.get("failures", {})),
        )
