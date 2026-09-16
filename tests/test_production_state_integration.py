import pytest

from studio.models import EpisodePlan, Scene, Shot
from studio.production_state import ProductionStateError, build_episode_production_state


def make_plan() -> EpisodePlan:
    return EpisodePlan(
        id="episode-1",
        story_id="story-1",
        title="Test Episode",
        scenes=(
            Scene(
                id="scene-1",
                order=1,
                description="Sasquatch enters the clearing.",
                shots=(
                    Shot(
                        id="shot-1",
                        scene_id="scene-1",
                        order=1,
                        purpose="Establish the clearing.",
                        duration_seconds=2.0,
                    ),
                    Shot(
                        id="shot-2",
                        scene_id="scene-1",
                        order=2,
                        purpose="Show Sasquatch looking around.",
                        duration_seconds=2.0,
                    ),
                ),
            ),
            Scene(
                id="scene-2",
                order=2,
                description="Sasquatch notices the moonberries.",
                shots=(
                    Shot(
                        id="shot-3",
                        scene_id="scene-2",
                        order=1,
                        purpose="Reveal the moonberries.",
                        duration_seconds=2.0,
                    ),
                ),
            ),
        ),
    )


def test_episode_plan_materializes_authoritative_episode_scene_shot_graph():
    state = build_episode_production_state("series-1", make_plan())

    assert state.series_id == "series-1"
    assert state.nodes["episode-1"].kind == "episode"
    assert state.nodes["scene-1"].kind == "scene"
    assert state.nodes["shot-2"].kind == "shot"

    assert state.dependencies_for("episode-1")[0].upstream_id == "series-1"
    assert [item.upstream_id for item in state.dependencies_for("scene-1")] == ["episode-1"]
    assert [item.upstream_id for item in state.dependencies_for("shot-2")] == ["scene-1"]


def test_episode_graph_is_episode_local():
    first = build_episode_production_state("series-1", make_plan())
    second_plan = make_plan()
    second_plan = EpisodePlan(
        id="episode-2",
        story_id=second_plan.story_id,
        title=second_plan.title,
        scenes=tuple(
            Scene(
                id=scene.id.replace("scene-", "scene-2-"),
                order=scene.order,
                description=scene.description,
                location_id=scene.location_id,
                time_of_day=scene.time_of_day,
                characters=scene.characters,
                events=scene.events,
                shots=tuple(
                    Shot(
                        id=shot.id.replace("shot-", "shot-2-"),
                        scene_id=scene.id.replace("scene-", "scene-2-"),
                        order=shot.order,
                        purpose=shot.purpose,
                        duration_seconds=shot.duration_seconds,
                        characters=shot.characters,
                        location_id=shot.location_id,
                        required_events=shot.required_events,
                        dialogue_ids=shot.dialogue_ids,
                        camera=shot.camera,
                        animation=shot.animation,
                        sound=shot.sound,
                    )
                    for shot in scene.shots
                ),
            )
            for scene in second_plan.scenes
        ),
    )
    second = build_episode_production_state("series-1", second_plan)

    assert all(
        node.episode_id in {None, "episode-1"}
        for node in first.nodes.values()
    )
    assert all(
        node.episode_id in {None, "episode-2"}
        for node in second.nodes.values()
    )


def test_episode_plan_rejects_duplicate_node_ids():
    plan = make_plan()
    duplicate_scene = Scene(
        id="scene-1",
        order=3,
        description="Duplicate scene id.",
    )
    invalid = EpisodePlan(
        id=plan.id,
        story_id=plan.story_id,
        title=plan.title,
        scenes=plan.scenes + (duplicate_scene,),
    )

    with pytest.raises(ProductionStateError, match="duplicate"):
        build_episode_production_state("series-1", invalid)
