from pathlib import Path

from studio.assets import index_assets, write_index
from studio.checkpoints import CheckpointStore
from studio.director import build_episode_plan
from studio.models import EpisodePlan
from studio.pipeline import Pipeline, RunState, STAGES
from studio.qc import release_ready, validate_episode_plan, validate_stage_outputs


def test_checkpoint_round_trip(tmp_path: Path):
    store = CheckpointStore(tmp_path)
    state = RunState("ep-1", completed={"interpret", "plan_episode"}, outputs={"interpret": "x"})
    store.save(state)
    restored = store.load("ep-1")
    assert restored.completed == state.completed
    assert restored.outputs == state.outputs


def test_pipeline_persists_after_each_stage(tmp_path: Path):
    store = CheckpointStore(tmp_path)
    calls = []
    handlers = {stage: (lambda state, stage=stage: calls.append(stage) or stage) for stage in STAGES}
    final = Pipeline(RunState("ep-2"), checkpoint=store).run(handlers)
    assert tuple(calls) == STAGES
    assert final.completed == set(STAGES)
    assert store.load("ep-2").completed == set(STAGES)


def test_director_preserves_event_and_dialogue_identity():
    interpretation = {
        "events": [
            {"id": "e1", "scene_id": "s1", "order": 1, "kind": "action", "description": "Juniper enters", "characters": [{"id": "juniper", "name": "Juniper"}]},
            {"id": "e2", "scene_id": "s1", "order": 2, "kind": "action", "description": "Juniper sits", "characters": [{"id": "juniper", "name": "Juniper"}]},
        ],
        "dialogue": [{"id": "d1", "scene_id": "s1", "text": "Hello."}],
        "review_items": [],
    }
    plan = build_episode_plan("story-1", "Test", interpretation)
    assert isinstance(plan, EpisodePlan)
    assert [event.id for event in plan.scenes[0].events] == ["e1", "e2"]
    assert plan.scenes[0].shots[0].dialogue_ids == ("d1",)


def test_qc_and_release_gate():
    interpretation = {"events": [{"id": "e1", "scene_id": "s1", "order": 1, "description": "Action"}], "dialogue": [], "review_items": []}
    plan = build_episode_plan("story-2", "Test", interpretation)
    qc = validate_episode_plan(plan)
    assert qc.passed
    outputs = {stage: "ok" for stage in ("interpret", "plan_episode", "build_scenes", "build_shots", "resolve_assets", "animate", "dialogue", "lip_sync", "sound_music", "composite", "edit")}
    assert validate_stage_outputs(outputs).passed
    assert release_ready(qc=qc, fidelity_passed=True, human_approved=True)
    assert not release_ready(qc=qc, fidelity_passed=True, human_approved=False)


def test_asset_index_records_content_hash(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "character.txt").write_text("creator asset", encoding="utf-8")
    records = index_assets(source)
    assert len(records) == 1
    assert records[0].creator_owned is True
    destination = tmp_path / "index.json"
    write_index(records, destination)
    assert destination.exists()
