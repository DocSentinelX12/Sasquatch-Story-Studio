"""Turn structured story interpretation into a production-safe episode plan."""

from __future__ import annotations

from typing import Any

from .contracts import content_hash, require_keys, require_nonempty_string, require_unique_ids
from .models import CharacterRef, EpisodePlan, Scene, Shot, StoryEvent


def build_episode_plan(story_id: str, title: str, interpretation: dict[str, Any]) -> EpisodePlan:
    """Build only from explicit structured interpretation data.

    The director may organize timing and production structure, but it never silently
    creates canon. Ambiguities remain review items.
    """
    require_nonempty_string(story_id, "story_id", "episode")
    require_nonempty_string(title, "title", "episode")
    require_keys(interpretation, ("events", "dialogue", "review_items"), "interpretation")

    events = list(interpretation["events"])
    require_unique_ids(events, "id", "interpretation.events")
    dialogue = list(interpretation["dialogue"])
    require_unique_ids(dialogue, "id", "interpretation.dialogue")

    scene_groups: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        scene_id = require_nonempty_string(event.get("scene_id"), "scene_id", "event")
        scene_groups.setdefault(scene_id, []).append(event)

    scenes: list[Scene] = []
    for scene_order, (scene_id, scene_events) in enumerate(scene_groups.items(), start=1):
        character_values: dict[str, CharacterRef] = {}
        canonical_shots: list[Shot] = []
        story_events: list[StoryEvent] = []
        for event_order, event in enumerate(sorted(scene_events, key=lambda item: item.get("order", 0)), start=1):
            story_event = StoryEvent(
                id=event["id"],
                scene_id=scene_id,
                order=event_order,
                kind=str(event.get("kind", "story_event")),
                description=str(event.get("description", "")),
                required=bool(event.get("required", True)),
                source_excerpt=event.get("source_excerpt"),
            )
            story_events.append(story_event)
            for character in event.get("characters", []):
                character_id = require_nonempty_string(character.get("id"), "id", "character")
                character_values.setdefault(
                    character_id,
                    CharacterRef(character_id, str(character.get("name", character_id)), character.get("role")),
                )

        duration = float(sum(max(0.1, float(event.get("duration_seconds", 2.0))) for event in scene_events))
        shot = Shot(
            id=f"{scene_id}-shot-001",
            scene_id=scene_id,
            order=1,
            purpose="Cover the canonical events in this scene without changing their order or meaning.",
            duration_seconds=duration,
            characters=tuple(character_values.values()),
            location_id=scene_events[0].get("location_id"),
            required_events=tuple(event.id for event in story_events if event.required),
            dialogue_ids=tuple(
                item["id"] for item in dialogue if item.get("scene_id") == scene_id
            ),
            camera={"status": "production_decision_required", "creative_review": True},
            animation={"status": "production_decision_required", "creative_review": True},
            sound={"status": "production_decision_required", "creative_review": True},
        )
        canonical_shots.append(shot)
        scenes.append(
            Scene(
                id=scene_id,
                order=scene_order,
                description=str(scene_events[0].get("scene_description", "")),
                location_id=scene_events[0].get("location_id"),
                time_of_day=scene_events[0].get("time_of_day"),
                characters=tuple(character_values.values()),
                events=tuple(story_events),
                shots=tuple(canonical_shots),
            )
        )

    review_items = tuple(str(item) if not isinstance(item, dict) else str(item.get("reason", item)) for item in interpretation["review_items"])
    fidelity_notes = (
        f"source_interpretation_hash={content_hash(interpretation)}",
        "No unreviewed creative invention is canonical.",
    )
    return EpisodePlan(
        id=f"episode-{story_id}",
        story_id=story_id,
        title=title,
        scenes=tuple(scenes),
        fidelity_notes=fidelity_notes,
        review_items=review_items,
    )
