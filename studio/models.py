"""Canonical production data structures.

These structures deliberately contain only production truth and provenance. Heavy
AI runtimes belong behind adapters and must not alter these contracts implicitly.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Literal
import json


@dataclass(frozen=True)
class Story:
    id: str
    title: str
    source_text: str
    source_kind: Literal["idea", "story", "script", "director_script"]
    author_version: str = "1"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StoryEvent:
    id: str
    scene_id: str
    order: int
    kind: str
    description: str
    required: bool = True
    source_excerpt: str | None = None


@dataclass(frozen=True)
class CharacterRef:
    id: str
    name: str
    role: str | None = None


@dataclass(frozen=True)
class Shot:
    id: str
    scene_id: str
    order: int
    purpose: str
    duration_seconds: float
    characters: tuple[CharacterRef, ...] = ()
    location_id: str | None = None
    required_events: tuple[str, ...] = ()
    dialogue_ids: tuple[str, ...] = ()
    camera: dict[str, Any] = field(default_factory=dict)
    animation: dict[str, Any] = field(default_factory=dict)
    sound: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Scene:
    id: str
    order: int
    description: str
    location_id: str | None = None
    time_of_day: str | None = None
    characters: tuple[CharacterRef, ...] = ()
    events: tuple[StoryEvent, ...] = ()
    shots: tuple[Shot, ...] = ()


@dataclass(frozen=True)
class EpisodePlan:
    id: str
    story_id: str
    title: str
    scenes: tuple[Scene, ...]
    fidelity_notes: tuple[str, ...] = ()
    review_items: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


@dataclass(frozen=True)
class ProductionManifest:
    episode_id: str
    story_id: str
    studio_version: str
    created_at: str
    inputs: dict[str, str]
    models: dict[str, str] = field(default_factory=dict)
    seeds: dict[str, int] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    completed_stages: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
