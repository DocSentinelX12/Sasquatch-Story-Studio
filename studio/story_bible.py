"""Canonical story bible contracts and fail-closed validation.

The story bible is creator-owned canon. This module validates identity and
cross-references without inventing missing creative material.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from .contracts import content_hash, require_nonempty_string, require_unique_ids


class StoryBibleIntegrityError(ValueError):
    """Raised when a story bible cannot safely enter production."""


@dataclass(frozen=True)
class BibleCharacter:
    id: str
    name: str
    role: str | None = None
    description: str | None = None
    traits: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class BibleLocation:
    id: str
    name: str
    description: str | None = None
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class BibleRule:
    id: str
    statement: str
    severity: str
    source_excerpt: str | None = None


@dataclass(frozen=True)
class StoryBible:
    id: str
    title: str
    version: str
    characters: tuple[BibleCharacter, ...]
    locations: tuple[BibleLocation, ...]
    rules: tuple[BibleRule, ...]
    style: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_hash(self) -> str:
        return content_hash(self.to_dict())

    def character_ids(self) -> frozenset[str]:
        return frozenset(character.id for character in self.characters)

    def location_ids(self) -> frozenset[str]:
        return frozenset(location.id for location in self.locations)


def build_story_bible(data: dict[str, Any]) -> StoryBible:
    """Validate and materialize a creator-supplied story bible.

    Missing creative details are rejected rather than guessed. Cross-reference
    validation is performed separately so a bible can be authored incrementally
    without silently fabricating characters or locations.
    """
    if not isinstance(data, dict):
        raise StoryBibleIntegrityError("story bible must be an object")
    required = ("id", "title", "version", "characters", "locations", "rules")
    missing = [key for key in required if key not in data]
    if missing:
        raise StoryBibleIntegrityError(f"story bible missing required fields: {missing}")

    bible_id = require_nonempty_string(data["id"], "id", "story_bible")
    title = require_nonempty_string(data["title"], "title", "story_bible")
    version = require_nonempty_string(data["version"], "version", "story_bible")

    characters = list(data["characters"])
    locations = list(data["locations"])
    rules = list(data["rules"])
    if not all(isinstance(item, dict) for item in characters + locations + rules):
        raise StoryBibleIntegrityError("story bible entries must be objects")
    require_unique_ids(characters, "id", "story_bible.characters")
    require_unique_ids(locations, "id", "story_bible.locations")
    require_unique_ids(rules, "id", "story_bible.rules")

    parsed_characters = tuple(
        BibleCharacter(
            id=require_nonempty_string(item["id"], "id", "character"),
            name=require_nonempty_string(item["name"], "name", "character"),
            role=item.get("role"),
            description=item.get("description"),
            traits=tuple(item.get("traits", ())),
            constraints=tuple(item.get("constraints", ())),
        )
        for item in characters
    )
    parsed_locations = tuple(
        BibleLocation(
            id=require_nonempty_string(item["id"], "id", "location"),
            name=require_nonempty_string(item["name"], "name", "location"),
            description=item.get("description"),
            constraints=tuple(item.get("constraints", ())),
        )
        for item in locations
    )
    parsed_rules = tuple(
        BibleRule(
            id=require_nonempty_string(item["id"], "id", "rule"),
            statement=require_nonempty_string(item["statement"], "statement", "rule"),
            severity=item.get("severity", "medium"),
            source_excerpt=item.get("source_excerpt"),
        )
        for item in rules
    )
    allowed_severities = {"canonical", "high", "medium", "low"}
    if any(rule.severity not in allowed_severities for rule in parsed_rules):
        raise StoryBibleIntegrityError("rule severity must be canonical, high, medium, or low")

    return StoryBible(
        id=bible_id,
        title=title,
        version=version,
        characters=parsed_characters,
        locations=parsed_locations,
        rules=parsed_rules,
        style=dict(data.get("style", {})),
        provenance=dict(data.get("provenance", {})),
    )


def validate_story_references(bible: StoryBible, *, events: list[dict[str, Any]]) -> None:
    """Reject references to characters or locations absent from canonical canon."""
    character_ids = bible.character_ids()
    location_ids = bible.location_ids()
    for event in events:
        for character in event.get("characters", []):
            if not isinstance(character, dict) or character.get("id") not in character_ids:
                raise StoryBibleIntegrityError(
                    f"event {event.get('id', '<unknown>')} references a character absent from the story bible"
                )
        location_id = event.get("location_id")
        if location_id is not None and location_id not in location_ids:
            raise StoryBibleIntegrityError(
                f"event {event.get('id', '<unknown>')} references a location absent from the story bible"
            )
