"""Stage 4 scene, storyboard, and shot contracts.

This module converts an already validated episode plan into a production-safe
storyboard boundary. It does not invent missing creative information. A shot
package is not ready for production until its required scene, references,
camera, description, and validation data are explicit and internally bound.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .contracts import content_hash, require_nonempty_string
from .models import EpisodePlan
from .story_bible import StoryBible, StoryBibleIntegrityError


class StoryboardIntegrityError(ValueError):
    """Raised when a scene/storyboard/shot package cannot be trusted."""


@dataclass(frozen=True)
class ShotPackage:
    """The complete creator/director-facing contract for one production shot.

    The fields are intentionally explicit. The studio may propose values, but
    absent values are not silently fabricated here.
    """

    id: str
    scene_id: str
    order: int
    version: int
    purpose: str
    story_event_ids: tuple[str, ...]
    dialogue_ids: tuple[str, ...]
    character_ids: tuple[str, ...]
    location_id: str | None
    prop_ids: tuple[str, ...]
    action: str
    performance: str
    camera: dict[str, Any]
    composition: str
    visual_style: dict[str, Any]
    lighting_weather: dict[str, Any]
    continuity: tuple[str, ...]
    negative_constraints: tuple[str, ...]
    sound_music: dict[str, Any]
    duration_seconds: float
    references: tuple[str, ...]
    validation: dict[str, Any]
    approval_state: str = "draft"
    overrides: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class StoryboardShot:
    id: str
    scene_id: str
    order: int
    package_hash: str
    status: str


@dataclass(frozen=True)
class StoryboardScene:
    id: str
    order: int
    description: str
    location_id: str | None
    character_ids: tuple[str, ...]
    shot_ids: tuple[str, ...]


@dataclass(frozen=True)
class Storyboard:
    episode_id: str
    story_id: str
    episode_plan_hash: str
    scenes: tuple[StoryboardScene, ...]
    shots: tuple[StoryboardShot, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_hash(self) -> str:
        return content_hash(self.to_dict())


def validate_episode_plan_for_storyboard(plan: EpisodePlan, bible: StoryBible) -> None:
    """Validate all scene/shot references before a storyboard can be built."""
    if not plan.story_id.strip():
        raise StoryboardIntegrityError("episode plan has no story_id")
    scene_ids: set[str] = set()
    event_ids: set[str] = set()
    dialogue_ids: set[str] = set()
    for scene in plan.scenes:
        if scene.id in scene_ids:
            raise StoryboardIntegrityError(f"duplicate scene id: {scene.id}")
        scene_ids.add(scene.id)
        if scene.order < 1:
            raise StoryboardIntegrityError(f"scene {scene.id} has invalid order")
        if not scene.description.strip():
            raise StoryboardIntegrityError(f"scene {scene.id} has no explicit description")
        if scene.location_id is not None and scene.location_id not in bible.location_ids():
            raise StoryboardIntegrityError(f"scene {scene.id} references an unknown location")
        scene_character_ids = {character.id for character in scene.characters}
        unknown_characters = scene_character_ids - bible.character_ids()
        if unknown_characters:
            raise StoryboardIntegrityError(
                f"scene {scene.id} references unknown characters: {sorted(unknown_characters)}"
            )
        for event in scene.events:
            if event.id in event_ids:
                raise StoryboardIntegrityError(f"duplicate event id in episode plan: {event.id}")
            event_ids.add(event.id)
        shot_ids: set[str] = set()
        previous_shot_order = 0
        for shot in scene.shots:
            if shot.id in shot_ids:
                raise StoryboardIntegrityError(f"duplicate shot id in scene {scene.id}: {shot.id}")
            shot_ids.add(shot.id)
            if shot.scene_id != scene.id:
                raise StoryboardIntegrityError(f"shot {shot.id} is bound to the wrong scene")
            if shot.order <= previous_shot_order:
                raise StoryboardIntegrityError(f"shots in scene {scene.id} are not strictly ordered")
            previous_shot_order = shot.order
            if shot.duration_seconds <= 0:
                raise StoryboardIntegrityError(f"shot {shot.id} has non-positive duration")
            if shot.location_id is not None and shot.location_id not in bible.location_ids():
                raise StoryboardIntegrityError(f"shot {shot.id} references an unknown location")
            shot_character_ids = {character.id for character in shot.characters}
            unknown_shot_characters = shot_character_ids - bible.character_ids()
            if unknown_shot_characters:
                raise StoryboardIntegrityError(
                    f"shot {shot.id} references unknown characters: {sorted(unknown_shot_characters)}"
                )
            for event_id in shot.required_events:
                if event_id not in {event.id for event in scene.events}:
                    raise StoryboardIntegrityError(
                        f"shot {shot.id} references event {event_id} outside its scene"
                    )
            for dialogue_id in shot.dialogue_ids:
                if dialogue_id in dialogue_ids:
                    raise StoryboardIntegrityError(f"dialogue id appears in multiple shots: {dialogue_id}")
                dialogue_ids.add(dialogue_id)
    scene_orders = [scene.order for scene in plan.scenes]
    if scene_orders != sorted(scene_orders) or len(set(scene_orders)) != len(scene_orders):
        raise StoryboardIntegrityError("episode scenes must have unique chronological order values")


def build_storyboard(plan: EpisodePlan, bible: StoryBible) -> Storyboard:
    """Create an ordered storyboard index without inventing shot decisions."""
    try:
        validate_episode_plan_for_storyboard(plan, bible)
    except StoryBibleIntegrityError as exc:
        raise StoryboardIntegrityError(str(exc)) from exc
    scenes = tuple(
        StoryboardScene(
            id=scene.id,
            order=scene.order,
            description=scene.description,
            location_id=scene.location_id,
            character_ids=tuple(character.id for character in scene.characters),
            shot_ids=tuple(shot.id for shot in scene.shots),
        )
        for scene in plan.scenes
    )
    shots = tuple(
        StoryboardShot(
            id=shot.id,
            scene_id=shot.scene_id,
            order=shot.order,
            package_hash=content_hash(asdict(shot)),
            status="requires_shot_package",
        )
        for scene in plan.scenes
        for shot in scene.shots
    )
    return Storyboard(
        episode_id=plan.id,
        story_id=plan.story_id,
        episode_plan_hash=content_hash(plan.to_dict()),
        scenes=scenes,
        shots=shots,
    )


def validate_shot_package(package: ShotPackage, plan: EpisodePlan, bible: StoryBible) -> None:
    """Fail closed unless the package is completely bound to canonical data."""
    require_nonempty_string(package.id, "id", "shot_package")
    require_nonempty_string(package.scene_id, "scene_id", "shot_package")
    require_nonempty_string(package.purpose, "purpose", "shot_package")
    require_nonempty_string(package.action, "action", "shot_package")
    require_nonempty_string(package.performance, "performance", "shot_package")
    require_nonempty_string(package.composition, "composition", "shot_package")
    if package.order < 1 or package.version < 1:
        raise StoryboardIntegrityError("shot package order and version must be positive integers")
    if package.duration_seconds <= 0:
        raise StoryboardIntegrityError("shot package duration must be positive")
    if not package.references:
        raise StoryboardIntegrityError("shot package requires explicit references")
    if not package.camera:
        raise StoryboardIntegrityError("shot package requires explicit camera data")
    if not package.validation:
        raise StoryboardIntegrityError("shot package requires explicit validation data")
    if package.approval_state not in {"draft", "review", "approved", "rejected", "remake_required"}:
        raise StoryboardIntegrityError(f"unknown shot package approval state: {package.approval_state}")

    scene = next((scene for scene in plan.scenes if scene.id == package.scene_id), None)
    if scene is None:
        raise StoryboardIntegrityError(f"shot package references unknown scene: {package.scene_id}")
    scene_event_ids = {event.id for event in scene.events}
    unknown_events = set(package.story_event_ids) - scene_event_ids
    if unknown_events:
        raise StoryboardIntegrityError(f"shot package references unknown scene events: {sorted(unknown_events)}")
    plan_dialogue_ids = {
        dialogue_id
        for candidate_scene in plan.scenes
        for candidate_shot in candidate_scene.shots
        for dialogue_id in candidate_shot.dialogue_ids
    }
    unknown_dialogue = set(package.dialogue_ids) - plan_dialogue_ids
    if unknown_dialogue:
        raise StoryboardIntegrityError(f"shot package references unknown dialogue ids: {sorted(unknown_dialogue)}")
    unknown_characters = set(package.character_ids) - bible.character_ids()
    if unknown_characters:
        raise StoryboardIntegrityError(f"shot package references unknown characters: {sorted(unknown_characters)}")
    if package.location_id is not None and package.location_id not in bible.location_ids():
        raise StoryboardIntegrityError(f"shot package references unknown location: {package.location_id}")
    if not isinstance(package.overrides, tuple):
        raise StoryboardIntegrityError("shot package overrides must be an immutable versioned tuple")


def make_shot_package(
    *,
    plan: EpisodePlan,
    bible: StoryBible,
    shot_id: str,
    version: int,
    purpose: str,
    story_event_ids: tuple[str, ...],
    dialogue_ids: tuple[str, ...],
    character_ids: tuple[str, ...],
    location_id: str | None,
    prop_ids: tuple[str, ...],
    action: str,
    performance: str,
    camera: dict[str, Any],
    composition: str,
    visual_style: dict[str, Any],
    lighting_weather: dict[str, Any],
    continuity: tuple[str, ...],
    negative_constraints: tuple[str, ...],
    sound_music: dict[str, Any],
    duration_seconds: float,
    references: tuple[str, ...],
    validation: dict[str, Any],
    approval_state: str = "draft",
    overrides: tuple[dict[str, Any], ...] = (),
    provenance: dict[str, Any] | None = None,
) -> ShotPackage:
    """Materialize a shot package only from supplied production decisions."""
    scene = next((scene for scene in plan.scenes if scene.id == plan_scene_id(plan, shot_id)), None)
    if scene is None:
        raise StoryboardIntegrityError(f"unknown shot id: {shot_id}")
    shot = next(shot for shot in scene.shots if shot.id == shot_id)
    package = ShotPackage(
        id=shot.id,
        scene_id=shot.scene_id,
        order=shot.order,
        version=version,
        purpose=purpose,
        story_event_ids=story_event_ids,
        dialogue_ids=dialogue_ids,
        character_ids=character_ids,
        location_id=location_id,
        prop_ids=prop_ids,
        action=action,
        performance=performance,
        camera=dict(camera),
        composition=composition,
        visual_style=dict(visual_style),
        lighting_weather=dict(lighting_weather),
        continuity=tuple(continuity),
        negative_constraints=tuple(negative_constraints),
        sound_music=dict(sound_music),
        duration_seconds=duration_seconds,
        references=tuple(references),
        validation=dict(validation),
        approval_state=approval_state,
        overrides=tuple(overrides),
        provenance=dict(provenance or {}),
    )
    validate_shot_package(package, plan, bible)
    return package


def plan_scene_id(plan: EpisodePlan, shot_id: str) -> str:
    for scene in plan.scenes:
        if any(shot.id == shot_id for shot in scene.shots):
            return scene.id
    raise StoryboardIntegrityError(f"unknown shot id: {shot_id}")
