"""Dependency-free production quality and release checks."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .models import EpisodePlan

@dataclass(frozen=True)
class QCResult:
    passed: bool
    checks: tuple[str, ...]
    failures: tuple[str, ...]

REQUIRED_OUTPUT_STAGES = ("interpret", "plan_episode", "build_scenes", "build_shots", "resolve_assets", "animate", "dialogue", "lip_sync", "sound_music", "composite", "edit", "master", "archive")

def validate_episode_plan(plan: EpisodePlan) -> QCResult:
    failures: list[str] = []
    checks: list[str] = []
    if not plan.story_id.strip(): failures.append("story_id is empty")
    checks.append("story identity")
    if not plan.scenes: failures.append("episode has no scenes")
    checks.append("scene presence")
    seen_scene_ids: set[str] = set()
    seen_event_ids: set[str] = set()
    seen_shot_ids: set[str] = set()
    for scene in plan.scenes:
        if scene.id in seen_scene_ids: failures.append(f"duplicate scene id: {scene.id}")
        seen_scene_ids.add(scene.id)
        if not scene.shots: failures.append(f"scene {scene.id} has no shots")
        for event in scene.events:
            if event.id in seen_event_ids: failures.append(f"duplicate event id: {event.id}")
            seen_event_ids.add(event.id)
            if event.required and not event.description.strip(): failures.append(f"required event {event.id} has no description")
        for shot in scene.shots:
            if shot.id in seen_shot_ids: failures.append(f"duplicate shot id: {shot.id}")
            seen_shot_ids.add(shot.id)
            if not shot.required_events: failures.append(f"shot {shot.id} covers no canonical event")
    checks.extend(("unique scene/event/shot identifiers", "shot coverage"))
    return QCResult(not failures, tuple(checks), tuple(failures))

def validate_stage_outputs(outputs: dict[str, Any]) -> QCResult:
    failures = [f"missing stage output: {stage}" for stage in REQUIRED_OUTPUT_STAGES if not outputs.get(stage)]
    return QCResult(not failures, ("required production stage outputs",), tuple(failures))

def release_ready(*, qc: QCResult, fidelity_passed: bool, human_approved: bool) -> bool:
    return qc.passed and fidelity_passed and human_approved
