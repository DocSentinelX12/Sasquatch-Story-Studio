"""Story interpretation boundary.

This module never invents production facts on its own. It packages the canonical
story for a verified LLM adapter and requires structured, provenance-bearing output.
"""

from dataclasses import dataclass
import hashlib
from typing import Any

from .ingest import StoryIntegrityError
from .llm import CANONICAL_LLM_INSTRUCTION, LLMRequest, LLMResponse, LLMRouter
from .models import Story


@dataclass(frozen=True)
class StoryInterpretation:
    story_id: str
    source_hash: str
    facts: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    dialogue: tuple[dict[str, Any], ...]
    review_items: tuple[dict[str, Any], ...]
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "story_id": self.story_id,
            "source_hash": self.source_hash,
            "facts": list(self.facts),
            "events": list(self.events),
            "dialogue": list(self.dialogue),
            "review_items": list(self.review_items),
            "provenance": self.provenance,
        }


def source_hash(story: Story) -> str:
    return hashlib.sha256(story.source_text.encode("utf-8")).hexdigest()


def interpret_story(story: Story, router: LLMRouter, *, output_schema: dict[str, Any] | None = None) -> StoryInterpretation:
    if not story.source_text.strip():
        raise StoryIntegrityError("cannot interpret an empty story")

    digest = source_hash(story)
    request = LLMRequest(
        task="interpret",
        system_instruction=CANONICAL_LLM_INSTRUCTION,
        user_input=story.source_text,
        canonical_source=story.source_text,
        output_schema=output_schema,
        temperature=0.0,
        metadata={"story_id": story.id, "source_hash": digest},
    )
    response: LLMResponse = router.generate(request)
    if response.structured_output is None:
        raise RuntimeError("story interpretation requires structured LLM output")

    data = response.structured_output
    required = ("facts", "events", "dialogue", "review_items")
    missing = [key for key in required if key not in data]
    if missing:
        raise RuntimeError(f"story interpretation missing required fields: {missing}")

    provenance = dict(response.provenance)
    provenance.setdefault("source_hash", digest)
    provenance.setdefault("story_id", story.id)
    provenance.setdefault("model_id", response.model_id)
    provenance.setdefault("model_version", response.model_version)
    provenance.setdefault("provider_id", response.provider_id)

    return StoryInterpretation(
        story_id=story.id,
        source_hash=digest,
        facts=tuple(data["facts"]),
        events=tuple(data["events"]),
        dialogue=tuple(data["dialogue"]),
        review_items=tuple(data["review_items"]),
        provenance=provenance,
    )
