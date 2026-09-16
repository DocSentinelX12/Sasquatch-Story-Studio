import pytest

from studio.models import CharacterRef, EpisodePlan, Scene, Shot, StoryEvent
from studio.production_graph import build_episode_production_state
from studio.production_state import ProductionStateError


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


def test_episode_graph_preserves_complete_node_local_canonical_data():
    plan = EpisodePlan(
        id="episode-1",
        story_id="story-1",
        title="Test Episode",
        scenes=(
            Scene(
                id="scene-1",
                order=1,
                description="Sasquatch enters the clearing.",
                location_id="forest-clearing",
                time_of_day="sunset",
                characters=(CharacterRef("sasquatch", "Sasquatch", "lead"),),
                events=(
                    StoryEvent(
                        id="event-1",
                        scene_id="scene-1",
                        order=1,
                        kind="action",
                        description="Sasquatch enters the clearing.",
                    ),
                ),
                shots=(
                    Shot(
                        id="shot-1",
                        scene_id="scene-1",
                        order=1,
                        purpose="Show the entrance.",
                        duration_seconds=2.5,
                        characters=(CharacterRef("sasquatch", "Sasquatch", "lead"),),
                        location_id="forest-clearing",
                        required_events=("event-1",),
                        dialogue_ids=("dialogue-1",),
                        camera={"framing": "wide", "movement": "track"},
                        animation={"action": "walk", "expression": "curious"},
                        sound={"ambience": "forest", "music": "none"},
                    ),
                ),
            ),
        ),
    )

    state = build_episode_production_state("series-1", plan)
    scene = state.nodes["scene-1"]
    shot = state.nodes["shot-1"]

    assert scene.data["time_of_day"] == "sunset"
    assert scene.data["characters"] == [{"id": "sasquatch", "name": "Sasquatch", "role": "lead"}]
    assert scene.data["events"][0]["id"] == "event-1"
    assert shot.data["characters"] == [{"id": "sasquatch", "name": "Sasquatch", "role": "lead"}]
    assert shot.data["dialogue_ids"] == ["dialogue-1"]
    assert shot.data["camera"] == {"framing": "wide", "movement": "track"}
    assert shot.data["animation"] == {"action": "walk", "expression": "curious"}
    assert shot.data["sound"] == {"ambience": "forest", "music": "none"}


def test_shot_changes_do_not_change_parent_node_content_hash():
    first = build_episode_production_state("series-1", make_plan())
    changed_plan = make_plan()
    original_scene = changed_plan.scenes[0]
    changed_shot = original_scene.shots[1]
    changed_scene = Scene(
        id=original_scene.id,
        order=original_scene.order,
        description=original_scene.description,
        location_id=original_scene.location_id,
        time_of_day=original_scene.time_of_day,
        characters=original_scene.characters,
        events=original_scene.events,
        shots=tuple(
            Shot(
                id=shot.id,
                scene_id=shot.scene_id,
                order=shot.order,
                purpose=("Changed purpose." if shot.id == changed_shot.id else shot.purpose),
                duration_seconds=shot.duration_seconds,
                characters=shot.characters,
                location_id=shot.location_id,
                required_events=shot.required_events,
                dialogue_ids=shot.dialogue_ids,
                camera=shot.camera,
                animation=shot.animation,
                sound=shot.sound,
            )
            for shot in original_scene.shots
        ),
    )
    changed_plan = EpisodePlan(
        id=changed_plan.id,
        story_id=changed_plan.story_id,
        title=changed_plan.title,
        scenes=(changed_scene, *changed_plan.scenes[1:]),
        fidelity_notes=changed_plan.fidelity_notes,
        review_items=changed_plan.review_items,
    )
    second = build_episode_production_state("series-1", changed_plan)

    assert first.nodes["episode-1"].content_hash == second.nodes["episode-1"].content_hash
    assert first.nodes["scene-1"].content_hash == second.nodes["scene-1"].content_hash
    assert first.nodes["shot-2"].content_hash != second.nodes["shot-2"].content_hash


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


def test_episode_plan_rejects_shot_bound_to_wrong_scene():
    plan = make_plan()
    invalid_shot = Shot(
        id="shot-invalid",
        scene_id="different-scene",
        order=1,
        purpose="Wrong scene binding.",
        duration_seconds=1.0,
    )
    invalid_scene = Scene(
        id="scene-3",
        order=3,
        description="Invalid binding.",
        shots=(invalid_shot,),
    )
    invalid = EpisodePlan(
        id=plan.id,
        story_id=plan.story_id,
        title=plan.title,
        scenes=plan.scenes + (invalid_scene,),
    )

    with pytest.raises(ProductionStateError, match="references scene"):
        build_episode_production_state("series-1", invalid)
