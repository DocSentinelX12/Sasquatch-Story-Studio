"""Bridge from validated episode plans to authoritative production state."""

from __future__ import annotations

from .models import EpisodePlan
from .production_state import Dependency, ProductionState, ProductionStateError, StateNode, hash_state


def build_episode_production_state(series_id: str, plan: EpisodePlan) -> ProductionState:
    """Materialize only existing series -> episode -> scene -> shot truth.

    This bridge deliberately does not invent assets, jobs, artifacts, approvals,
    or cross-episode relationships. Those become graph nodes only when their
    corresponding production records actually exist.
    """
    if not series_id.strip():
        raise ProductionStateError("series_id is required")
    if not plan.id.strip():
        raise ProductionStateError("episode plan id is required")

    state = ProductionState(series_id)
    series_data = {"id": series_id, "kind": "series"}
    state.add_node(StateNode(
        node_id=series_id,
        kind="series",
        revision=1,
        content_hash=hash_state(series_data),
        episode_id=None,
        status="canonical",
        data=series_data,
    ))

    seen_ids: set[str] = {series_id}

    def add_unique(node: StateNode) -> None:
        if node.node_id in seen_ids:
            raise ProductionStateError(f"duplicate node id in episode plan: {node.node_id}")
        seen_ids.add(node.node_id)
        state.add_node(node)

    episode_data = {
        "id": plan.id,
        "story_id": plan.story_id,
        "title": plan.title,
        "plan_hash": hash_state(plan.to_dict()),
    }
    add_unique(StateNode(
        node_id=plan.id,
        kind="episode",
        revision=1,
        content_hash=hash_state(episode_data),
        episode_id=plan.id,
        status="canonical",
        data=episode_data,
    ))
    state.add_dependency(Dependency(series_id, 1, plan.id))

    for scene in plan.scenes:
        scene_data = {
            "id": scene.id,
            "episode_id": plan.id,
            "order": scene.order,
            "description": scene.description,
            "location_id": scene.location_id,
        }
        add_unique(StateNode(
            node_id=scene.id,
            kind="scene",
            revision=1,
            content_hash=hash_state(scene_data),
            episode_id=plan.id,
            status="canonical",
            data=scene_data,
        ))
        state.add_dependency(Dependency(plan.id, 1, scene.id))

        for shot in scene.shots:
            shot_data = {
                "id": shot.id,
                "episode_id": plan.id,
                "scene_id": scene.id,
                "order": shot.order,
                "purpose": shot.purpose,
                "duration_seconds": shot.duration_seconds,
                "required_events": list(shot.required_events),
                "dialogue_ids": list(shot.dialogue_ids),
                "location_id": shot.location_id,
                "camera": shot.camera,
                "animation": shot.animation,
                "sound": shot.sound,
            }
            add_unique(StateNode(
                node_id=shot.id,
                kind="shot",
                revision=1,
                content_hash=hash_state(shot_data),
                episode_id=plan.id,
                status="canonical",
                data=shot_data,
            ))
            state.add_dependency(Dependency(scene.id, 1, shot.id))

    return state
