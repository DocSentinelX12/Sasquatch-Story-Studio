from studio.director import build_episode_plan

def test_director_creates_one_shot_per_canonical_event():
    interpretation = {"events": [{"id": "e1", "scene_id": "s1", "order": 1, "description": "A", "characters": []}, {"id": "e2", "scene_id": "s1", "order": 2, "description": "B", "characters": []}], "dialogue": [], "review_items": []}
    plan = build_episode_plan("story", "Episode", interpretation)
    assert len(plan.scenes) == 1
    assert [shot.required_events for shot in plan.scenes[0].shots] == [("e1",), ("e2",)]
