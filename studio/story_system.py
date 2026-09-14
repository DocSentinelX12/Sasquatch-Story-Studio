"""Authoritative story-to-episode boundary for stage 3.

This layer binds creator source, story bible, interpretation, episode planning,
and deterministic fidelity checks. It never fills missing creative data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import content_hash
from .director import build_episode_plan
from .fidelity import FidelityReport, validate_episode_plan_fidelity
from .ingest import StoryIntegrityError
from .interpreter import StoryInterpretation, source_hash
from .models import EpisodePlan, Story
from .story_bible import StoryBible, StoryBibleIntegrityError, validate_story_references


class StorySystemIntegrityError(ValueError):
    """Raised when canonical story material cannot safely become an episode."""


@dataclass(frozen=True)
class EpisodeDraft:
    story: Story
    story_bible_hash: str
    interpretation_hash: str
    plan: EpisodePlan
    fidelity: FidelityReport


def validate_interpretation(
    story: Story,
    bible: StoryBible,
    interpretation: StoryInterpretation | dict[str, Any],
) -> None:
    """Fail closed on source drift, malformed ordering, or unknown canon refs."""
    data = interpretation.to_dict() if isinstance(interpretation, StoryInterpretation) else interpretation
    if not isinstance(data, dict):
        raise StorySystemIntegrityError("interpretation must be an object")
    expected_hash = source_hash(story)
    if data.get("source_hash") != expected_hash:
        raise StorySystemIntegrityError("interpretation source_hash does not match the canonical story")
    if data.get("story_id") != story.id:
        raise StorySystemIntegrityError("interpretation story_id does not match the canonical story")

    events = data.get("events")
    dialogue = data.get("dialogue")
    if not isinstance(events, list) or not isinstance(dialogue, list):
        raise StorySystemIntegrityError("interpretation events and dialogue must be arrays")
    _require_unique_string_ids(events, "events")
    _require_unique_string_ids(dialogue, "dialogue")
    validate_story_references(bible, events=events)

    orders = [event.get("order") for event in events]
    if any(not isinstance(order, int) or order < 1 for order in orders):
        raise StorySystemIntegrityError("every canonical event must have a positive integer order")
    if orders != sorted(orders):
        raise StorySystemIntegrityError("canonical event order must already be chronological")
    if len(set(orders)) != len(orders):
        raise StorySystemIntegrityError("canonical event order values must be unique")

    event_ids = {event["id"] for event in events}
    for item in dialogue:
        event_id = item.get("event_id")
        if event_id is not None and event_id not in event_ids:
            raise StorySystemIntegrityError(
                f"dialogue {item['id']} references an event absent from the canonical interpretation"
            )
        if not isinstance(item.get("speaker"), str) or not item["speaker"].strip():
            raise StorySystemIntegrityError(f"dialogue {item['id']} has no speaker")
        if not isinstance(item.get("text"), str):
            raise StorySystemIntegrityError(f"dialogue {item['id']} has invalid text")
        if "source_text" not in item:
            raise StorySystemIntegrityError(f"dialogue {item['id']} has no canonical source_text")


def build_episode_draft(
    story: Story,
    bible: StoryBible,
    interpretation: StoryInterpretation | dict[str, Any],
) -> EpisodeDraft:
    """Build a production draft only after all canonical safeguards pass."""
    if not story.source_text.strip():
        raise StoryIntegrityError("cannot build an episode from an empty story")
    try:
        validate_interpretation(story, bible, interpretation)
    except (StoryBibleIntegrityError, StorySystemIntegrityError) as exc:
        raise StorySystemIntegrityError(str(exc)) from exc

    data = interpretation.to_dict() if isinstance(interpretation, StoryInterpretation) else interpretation
    plan = build_episode_plan(story.id, story.title, data)
    fidelity = validate_episode_plan_fidelity(plan)
    if not fidelity.passed:
        raise StorySystemIntegrityError(
            f"episode plan failed deterministic story fidelity: missing={fidelity.missing_required_events}, "
            f"unapproved={fidelity.unapproved_events}"
        )
    return EpisodeDraft(
        story=story,
        story_bible_hash=bible.content_hash(),
        interpretation_hash=content_hash(data),
        plan=plan,
        fidelity=fidelity,
    )


def _require_unique_string_ids(items: list[dict[str, Any]], context: str) -> None:
    ids = [item.get("id") for item in items]
    if any(not isinstance(item_id, str) or not item_id.strip() for item_id in ids):
        raise StorySystemIntegrityError(f"{context} contains an item without a valid id")
    if len(ids) != len(set(ids)):
        raise StorySystemIntegrityError(f"{context} contains duplicate ids")
