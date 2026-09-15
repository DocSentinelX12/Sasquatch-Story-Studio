import hashlib

import pytest

from studio.ingest import ingest_story
from studio.interpreter import StoryInterpretation
from studio.story_bible import build_story_bible
from studio.story_system import StorySystemIntegrityError, build_episode_draft, validate_interpretation


def _story_and_bible():
    story = ingest_story(
        story_id="ep001",
        title="The Great Moonberry Bounce",
        text="Yeti enters the forest and finds a moonberry.",
        source_kind="story",
    )
    bible = build_story_bible(
        {
            "id": "series",
            "title": "Series Bible",
            "version": "1",
            "characters": [{"id": "yeti", "name": "Yeti"}],
            "locations": [{"id": "forest", "name": "Forest"}],
            "rules": [],
        }
    )
    return story, bible


def _interpretation(story):
    digest = hashlib.sha256(story.source_text.encode()).hexdigest()
    return StoryInterpretation(
        story_id=story.id,
        source_hash=digest,
        facts=[{"id": "f1", "statement": "Yeti enters the forest", "source": {"excerpt": "Yeti enters the forest"}}],
        events=[
            {
                "id": "e1",
                "scene_id": "s1",
                "order": 1,
                "description": "Yeti enters the forest",
                "scene_description": "Yeti enters the forest and discovers a moonberry in the forest.",
                "characters": [{"id": "yeti", "name": "Yeti"}],
                "location_id": "forest",
                "source_excerpt": "Yeti enters the forest",
            },
            {
                "id": "e2",
                "scene_id": "s1",
                "order": 2,
                "description": "Yeti finds a moonberry",
                "scene_description": "Yeti enters the forest and discovers a moonberry in the forest.",
                "characters": [{"id": "yeti", "name": "Yeti"}],
                "location_id": "forest",
                "source_excerpt": "finds a moonberry",
            },
        ],
        dialogue=[],
        review_items=[],
        provenance={"provider_id": "test", "model_id": "test", "model_version": "1"},
    )


def test_build_episode_draft_binds_story_bible_and_fidelity():
    story, bible = _story_and_bible()
    draft = build_episode_draft(story, bible, _interpretation(story))
    assert draft.plan.story_id == story.id
    assert draft.fidelity.passed
    assert len(draft.plan.scenes[0].shots) == 2
    assert len(draft.story_bible_hash) == 64
    assert len(draft.interpretation_hash) == 64


def test_interpretation_source_drift_is_rejected():
    story, bible = _story_and_bible()
    interpretation = _interpretation(story)
    drifted = StoryInterpretation(
        story_id=interpretation.story_id,
        source_hash="0" * 64,
        facts=interpretation.facts,
        events=interpretation.events,
        dialogue=interpretation.dialogue,
        review_items=interpretation.review_items,
        provenance=interpretation.provenance,
    )
    with pytest.raises(StorySystemIntegrityError, match="source_hash"):
        validate_interpretation(story, bible, drifted)


def test_event_order_must_be_chronological():
    story, bible = _story_and_bible()
    interpretation = _interpretation(story)
    reversed_events = tuple(reversed(interpretation.events))
    broken = StoryInterpretation(
        story_id=interpretation.story_id,
        source_hash=interpretation.source_hash,
        facts=interpretation.facts,
        events=reversed_events,
        dialogue=interpretation.dialogue,
        review_items=interpretation.review_items,
        provenance=interpretation.provenance,
    )
    with pytest.raises(StorySystemIntegrityError, match="chronological"):
        validate_interpretation(story, bible, broken)
