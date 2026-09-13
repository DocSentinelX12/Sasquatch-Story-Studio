"""Story ingestion and conservative interpretation helpers."""

from .models import Story


class StoryIntegrityError(ValueError):
    """Raised when a story cannot safely enter production."""


def ingest_story(*, story_id: str, title: str, text: str, source_kind: str) -> Story:
    if not story_id.strip():
        raise StoryIntegrityError("story_id is required")
    if not title.strip():
        raise StoryIntegrityError("title is required")
    if not text.strip():
        raise StoryIntegrityError("source story is empty")
    allowed = {"idea", "story", "script", "director_script"}
    if source_kind not in allowed:
        raise StoryIntegrityError(f"source_kind must be one of {sorted(allowed)}")
    return Story(story_id, title, text, source_kind)  # type: ignore[arg-type]


def canonical_instruction() -> str:
    return (
        "The creator source is canonical. Extract production facts without silently "
        "inventing plot events. Any proposed creative change must be marked for review."
    )
