import pytest

from studio.scene_storyboard import (
    StoryboardIntegrityError,
    build_storyboard,
    make_shot_package,
    reorder_shots,
    validate_episode_plan_for_storyboard,
)
from studio.story_system import build_episode_draft
from tests.test_story_system import _interpretation, _story_and_bible


def test_storyboard_preserves_scene_and_shot_order_and_binds_plan_hash():
    story, bible = _story_and_bible()
    draft = build_episode_draft(story, bible, _interpretation(story))
    storyboard = build_storyboard(draft.plan, bible)
    assert [scene.id for scene in storyboard.scenes] == ["s1"]
    assert [shot.order for shot in storyboard.shots] == [1, 2]
    assert storyboard.episode_plan_hash
    assert all(shot.status == "requires_shot_package" for shot in storyboard.shots)


def test_storyboard_rejects_missing_scene_description():
    story, bible = _story_and_bible()
    draft = build_episode_draft(story, bible, _interpretation(story))
    broken_scene = draft.plan.scenes[0]
    from studio.models import EpisodePlan, Scene
    broken = EpisodePlan(
        id=draft.plan.id,
        story_id=draft.plan.story_id,
        title=draft.plan.title,
        scenes=(Scene(
            id=broken_scene.id,
            order=broken_scene.order,
            description="",
            location_id=broken_scene.location_id,
            time_of_day=broken_scene.time_of_day,
            characters=broken_scene.characters,
            events=broken_scene.events,
            shots=broken_scene.shots,
        ),),
    )
    with pytest.raises(StoryboardIntegrityError, match="description"):
        validate_episode_plan_for_storyboard(broken, bible)


def test_safe_shot_reorder_preserves_canonical_event_sequence():
    story, bible = _story_and_bible()
    draft = build_episode_draft(story, bible, _interpretation(story))
    original = draft.plan.scenes[0].shots
    same_order = reorder_shots(draft.plan, "s1", tuple(shot.id for shot in original))
    assert [shot.id for shot in same_order.scenes[0].shots] == [shot.id for shot in original]
    with pytest.raises(StoryboardIntegrityError, match="canonical story event order"):
        reorder_shots(draft.plan, "s1", tuple(shot.id for shot in reversed(original)))


def test_shot_package_requires_real_production_sections_and_references():
    story, bible = _story_and_bible()
    draft = build_episode_draft(story, bible, _interpretation(story))
    shot = draft.plan.scenes[0].shots[0]
    package = make_shot_package(
        plan=draft.plan,
        bible=bible,
        shot_id=shot.id,
        version=1,
        shot_type="establishing",
        purpose="Establish Yeti entering the forest.",
        story_event_ids=("e1",),
        dialogue_ids=(),
        dialogue_narration_ids=(),
        character_ids=("yeti",),
        location_id="forest",
        prop_ids=(),
        action="Yeti enters the forest.",
        performance="Curious, alert movement.",
        camera={"shot_size": "wide", "movement": "static"},
        composition="Yeti framed clearly against the forest entrance.",
        visual_style={"style": "series_canon"},
        lighting_weather={"lighting": "daylight", "weather": "clear"},
        continuity=("Maintain approved Yeti design.",),
        negative_constraints=("Do not introduce unapproved characters.",),
        sound_music={"ambience": "forest"},
        duration_seconds=2.0,
        references=("approved:yeti", "approved:forest"),
        validation={"story_event_bound": True, "references_resolved": True},
    )
    assert package.version == 1
    assert package.shot_type == "establishing"
    assert package.content_hash()


def test_shot_package_rejects_unknown_canon_reference():
    story, bible = _story_and_bible()
    draft = build_episode_draft(story, bible, _interpretation(story))
    shot = draft.plan.scenes[0].shots[0]
    with pytest.raises(StoryboardIntegrityError, match="unknown characters"):
        make_shot_package(
            plan=draft.plan,
            bible=bible,
            shot_id=shot.id,
            version=1,
            shot_type="wide",
            purpose="Test",
            story_event_ids=("e1",),
            dialogue_ids=(),
            dialogue_narration_ids=(),
            character_ids=("invented",),
            location_id="forest",
            prop_ids=(),
            action="No invented action.",
            performance="Explicit performance.",
            camera={"shot_size": "wide"},
            composition="Explicit composition.",
            visual_style={},
            lighting_weather={},
            continuity=(),
            negative_constraints=(),
            sound_music={},
            duration_seconds=2,
            references=("approved:yeti",),
            validation={"references_resolved": True},
        )
