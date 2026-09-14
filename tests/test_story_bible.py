import pytest

from studio.story_bible import StoryBibleIntegrityError, build_story_bible, validate_story_references


def test_story_bible_requires_real_canon_entries():
    bible = build_story_bible(
        {
            "id": "series",
            "title": "Series Bible",
            "version": "1",
            "characters": [{"id": "yeti", "name": "Yeti"}],
            "locations": [{"id": "forest", "name": "Forest"}],
            "rules": [{"id": "rule-1", "statement": "Creator canon is authoritative", "severity": "canonical"}],
        }
    )
    assert bible.character_ids() == {"yeti"}
    assert bible.location_ids() == {"forest"}
    assert len(bible.content_hash()) == 64


def test_story_bible_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate id"):
        build_story_bible(
            {
                "id": "series",
                "title": "Series Bible",
                "version": "1",
                "characters": [
                    {"id": "yeti", "name": "Yeti"},
                    {"id": "yeti", "name": "Yeti duplicate"},
                ],
                "locations": [],
                "rules": [],
            }
        )


def test_story_references_fail_closed_for_unknown_character_or_location():
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
    with pytest.raises(StoryBibleIntegrityError):
        validate_story_references(
            bible,
            events=[{"id": "e1", "characters": [{"id": "unknown"}], "location_id": "forest"}],
        )
    with pytest.raises(StoryBibleIntegrityError):
        validate_story_references(
            bible,
            events=[{"id": "e1", "characters": [{"id": "yeti"}], "location_id": "unknown"}],
        )
