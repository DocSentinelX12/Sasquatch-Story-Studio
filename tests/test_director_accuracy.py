from studio.director import build_episode_plan


def test_director_orders_scenes_by_canonical_event_order_not_input_order():
    interpretation = {
        "events": [
            {"id": "e2", "scene_id": "scene-2", "order": 2, "description": "Second"},
            {"id": "e1", "scene_id": "scene-1", "order": 1, "description": "First"},
        ],
        "dialogue": [],
        "review_items": [],
    }
    plan = build_episode_plan("story", "Story", interpretation)
    assert [scene.id for scene in plan.scenes] == ["scene-1", "scene-2"]
    assert [scene.events[0].order for scene in plan.scenes] == [1, 2]


def test_director_preserves_unbound_scene_dialogue_for_review_without_inventing_timing():
    interpretation = {
        "events": [
            {"id": "e1", "scene_id": "scene-1", "order": 1, "description": "Action"},
        ],
        "dialogue": [
            {"id": "d1", "scene_id": "scene-1", "order": 1, "speaker": "Yeti", "text": "Hello"},
        ],
        "review_items": [],
    }
    plan = build_episode_plan("story", "Story", interpretation)
    assert plan.scenes[0].shots[0].dialogue_ids == ("d1",)
    assert "d1" in plan.review_items[-1]
    assert "scene-level dialogue anchor" in plan.review_items[-1]


def test_director_scopes_shot_characters_to_the_canonical_event():
    interpretation = {
        "events": [
            {"id": "e1", "scene_id": "scene-1", "order": 1, "description": "Yeti", "characters": [{"id": "yeti", "name": "Yeti"}]},
            {"id": "e2", "scene_id": "scene-1", "order": 2, "description": "Juniper", "characters": [{"id": "juniper", "name": "Juniper"}]},
        ],
        "dialogue": [],
        "review_items": [],
    }
    plan = build_episode_plan("story", "Story", interpretation)
    assert tuple(c.id for c in plan.scenes[0].shots[0].characters) == ("yeti",)
    assert tuple(c.id for c in plan.scenes[0].shots[1].characters) == ("juniper",)
