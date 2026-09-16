"""Bridge validated episode plans into authoritative production state.

The bridge preserves the existing EpisodePlan model as the source of truth while
materializing node-local canonical state. Parent nodes do not embed child
content, so a surgical shot change does not implicitly rewrite the episode or
scene revision and invalidate unrelated downstream work.
"""
from __future__ import annotations

from dataclasses import asdict

from .models import EpisodePlan, Scene, Shot
from .production_state import (
    Dependency,
    ProductionState,
    ProductionStateError,
    StateNode,
    hash_state,
)


def _scene_data(plan: EpisodePlan, scene: Scene) -> dict[str, object]:
    """Return only canonical state owned by the scene itself."""
    return {
        "id": scene.id,
        "episode_id": plan.id,
        "order": scene.order,
        "description": scene.description,
        "location_id": scene.location_id,
        "time_of_day": scene.time_of_day,
        "characters": [asdict(character) for character in scene.characters],
        "events": [asdict(event) for event in scene.events],
    }


def _shot_data(plan: EpisodePlan, scene: Scene, shot: Shot) -> dict[str, object]:
    """Return the complete canonical state owned by the shot itself."""
    data = asdict(shot)
    data["episode_id"] = plan.id
    data["scene_id"] = scene.id
    return data


def build_episode_production_state(series_id: str, plan: EpisodePlan) -> ProductionState:
    """Materialize existing series -> episode -> scene -> shot truth.

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
    state.add_node(
        StateNode(
            node_id=series_id,
            kind="series",
            revision=1,
            content_hash=hash_state(series_data),
            episode_id=None,
            status="canonical",
            data=series_data,
        )
    )

    seen_ids: set[str] = {series_id}

    def add_unique(node: StateNode) -> None:
        if node.node_id in seen_ids:
            raise ProductionStateError(f"duplicate node id in episode plan: {node.node_id}")
        seen_ids.add(node.node_id)
        state.add_node(node)

    # Episode content owns episode identity and source-story identity only. The
    # complete EpisodePlan hash is provenance, not episode-node content, because
    # embedding child scene/shot content would make surgical child edits appear
    # to change the parent revision.
    episode_data = {
        "id": plan.id,
        "story_id": plan.story_id,
        "title": plan.title,
    }
    add_unique(
        StateNode(
            node_id=plan.id,
            kind="episode",
            revision=1,
            content_hash=hash_state(episode_data),
            episode_id=plan.id,
            status="canonical",
            data=episode_data,
        )
    )
    state.add_dependency(Dependency(series_id, 1, plan.id))

    for scene in plan.scenes:
        scene_data = _scene_data(plan, scene)
        add_unique(
            StateNode(
                node_id=scene.id,
                kind="scene",
                revision=1,
                content_hash=hash_state(scene_data),
                episode_id=plan.id,
                status="canonical",
                data=scene_data,
            )
        )
        state.add_dependency(Dependency(plan.id, 1, scene.id))

        for shot in scene.shots:
            if shot.scene_id != scene.id:
                raise ProductionStateError(
                    f"shot {shot.id} references scene {shot.scene_id}, not {scene.id}"
                )
            shot_data = _shot_data(plan, scene, shot)
            add_unique(
                StateNode(
                    node_id=shot.id,
                    kind="shot",
                    revision=1,
                    content_hash=hash_state(shot_data),
                    episode_id=plan.id,
                    status="canonical",
                    data=shot_data,
                )
            )
            state.add_dependency(Dependency(scene.id, 1, shot.id))

    return state
