"""Turn structured story interpretation into a production-safe episode plan."""
from __future__ import annotations

from typing import Any

from .contracts import content_hash, require_keys, require_nonempty_string, require_unique_ids
from .models import CharacterRef, EpisodePlan, Scene, Shot, StoryEvent


def build_episode_plan(story_id: str, title: str, interpretation: dict[str, Any]) -> EpisodePlan:
    """Create deterministic scenes and shots from canonical story events.

    Production decisions are explicit review items. The director never silently
    creates, removes, reorders, or changes canon.
    """
    require_nonempty_string(story_id, "story_id", "episode")
    require_nonempty_string(title, "title", "episode")
    require_keys(interpretation, ("events", "dialogue", "review_items"), "interpretation")
    events = list(interpretation["events"])
    dialogue = list(interpretation["dialogue"])
    require_unique_ids(events, "id", "interpretation.events")
    require_unique_ids(dialogue, "id", "interpretation.dialogue")

    scene_groups: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        scene_id = require_nonempty_string(event.get("scene_id"), "scene_id", "event")
        scene_groups.setdefault(scene_id, []).append(event)

    # Scene order is derived from canonical event order, never dictionary insertion order.
    ordered_scene_groups = sorted(
        scene_groups.items(),
        key=lambda item: min(int(event.get("order", 0)) for event in item[1]),
    )
    scenes: list[Scene] = []
    review_items = [
        str(item) if not isinstance(item, dict) else str(item.get("reason", item))
        for item in interpretation["review_items"]
    ]

    for scene_order, (scene_id, scene_events) in enumerate(ordered_scene_groups, start=1):
        scene_events = sorted(scene_events, key=lambda item: item.get("order", 0))
        character_values: dict[str, CharacterRef] = {}
        story_events: list[StoryEvent] = []
        shots: list[Shot] = []
        scene_dialogue = [item for item in dialogue if item.get("scene_id") == scene_id]
        assigned_dialogue: set[str] = set()

        for event in scene_events:
            canonical_order = event["order"]
            story_event = StoryEvent(
                id=event["id"], scene_id=scene_id, order=canonical_order,
                kind=str(event.get("kind", "story_event")),
                description=str(event.get("description", "")),
                required=bool(event.get("required", True)), source_excerpt=event.get("source_excerpt"),
            )
            story_events.append(story_event)

            event_characters: list[CharacterRef] = []
            for character in event.get("characters", []):
                character_id = require_nonempty_string(character.get("id"), "id", "character")
                reference = CharacterRef(
                    character_id,
                    str(character.get("name", character_id)),
                    character.get("role"),
                )
                character_values.setdefault(character_id, reference)
                event_characters.append(character_values[character_id])

            # Explicit event or shot bindings are authoritative. A dialogue item that
            # is only scene-bound is preserved on the first shot as a scene-level
            # dialogue anchor, and the required review item makes the unresolved
            # timing decision auditable instead of silently inventing event ownership.
            event_dialogue = tuple(
                item["id"] for item in scene_dialogue
                if item.get("event_id") == event["id"] or item.get("shot_id") == f"{scene_id}-shot-{canonical_order:03d}"
            )
            assigned_dialogue.update(event_dialogue)
            duration = max(0.1, float(event.get("duration_seconds", 2.0)))
            shots.append(
                Shot(
                    id=f"{scene_id}-shot-{canonical_order:03d}",
                    scene_id=scene_id,
                    order=canonical_order,
                    purpose=f"Depict canonical event {event['id']} without changing its meaning.",
                    duration_seconds=duration,
                    characters=tuple(event_characters),
                    location_id=event.get("location_id"),
                    required_events=(event["id"],),
                    dialogue_ids=event_dialogue,
                    camera={"status": "production_decision_required", "creative_review": True},
                    animation={"status": "production_decision_required", "creative_review": True},
                    sound={"status": "production_decision_required", "creative_review": True},
                )
            )

        # Scene-level dialogue has no canonical event ownership. Preserve its identity
        # deterministically on the first shot while requiring an explicit production
        # review before timing can be considered final.
        scene_level = tuple(
            item["id"]
            for item in scene_dialogue
            if "event_id" not in item and "shot_id" not in item
        )
        if scene_level and shots:
            first = shots[0]
            shots[0] = Shot(
                id=first.id,
                scene_id=first.scene_id,
                order=first.order,
                purpose=first.purpose,
                duration_seconds=first.duration_seconds,
                characters=first.characters,
                location_id=first.location_id,
                required_events=first.required_events,
                dialogue_ids=tuple((*first.dialogue_ids, *scene_level)),
                camera=first.camera,
                animation=first.animation,
                sound=first.sound,
            )
            assigned_dialogue.update(scene_level)
            review_items.append(
                f"CREATIVE REVIEW REQUIRED: scene {scene_id} dialogue mapping is not explicit; "
                f"preserved as a scene-level dialogue anchor on {first.id}: {scene_level}."
            )

        unassigned = tuple(item["id"] for item in scene_dialogue if item["id"] not in assigned_dialogue)
        if unassigned:
            review_items.append(
                f"CREATIVE REVIEW REQUIRED: scene {scene_id} dialogue mapping is not explicit; "
                f"dialogue remains unassigned: {unassigned}."
            )

        scenes.append(
            Scene(
                id=scene_id,
                order=scene_order,
                description=str(scene_events[0].get("scene_description", "")),
                location_id=scene_events[0].get("location_id"),
                time_of_day=scene_events[0].get("time_of_day"),
                characters=tuple(character_values.values()),
                events=tuple(story_events),
                shots=tuple(shots),
            )
        )

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
        review_items=tuple(review_items),
    )
