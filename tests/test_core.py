import pytest

from studio.ingest import StoryIntegrityError, ingest_story
from studio.models import CharacterRef, EpisodePlan, Scene, Shot, StoryEvent
from studio.pipeline import Pipeline, RunState, STAGES


def test_story_requires_real_source_text():
    with pytest.raises(StoryIntegrityError):
        ingest_story(story_id="ep-1", title="Test", text="", source_kind="story")


def test_episode_plan_round_trips_to_dict():
    shot = Shot(id="shot-1", scene_id="scene-1", order=1, purpose="establish", duration_seconds=2.0)
    scene = Scene(id="scene-1", order=1, description="A room", shots=(shot,))
    plan = EpisodePlan(id="ep-1", story_id="story-1", title="Test", scenes=(scene,))
    assert plan.to_dict()["scenes"][0]["shots"][0]["id"] == "shot-1"


def test_pipeline_resumes_completed_stages():
    state = RunState("ep-1", completed={"interpret"})
    seen = []
    handlers = {stage: (lambda _state, stage=stage: seen.append(stage)) for stage in STAGES}
    Pipeline(state).run(handlers)
    assert "interpret" not in seen
    assert seen == list(STAGES[1:])
    assert state.completed == set(STAGES)


def test_pipeline_records_failure_without_marking_stage_complete():
    state = RunState("ep-1")

    def fail(_state):
        raise RuntimeError("render failed")

    handlers = {stage: (lambda _state: None) for stage in STAGES}
    handlers["interpret"] = fail
    with pytest.raises(RuntimeError):
        Pipeline(state).run(handlers)
    assert "interpret" not in state.completed
    assert "render failed" in state.failures["interpret"]
