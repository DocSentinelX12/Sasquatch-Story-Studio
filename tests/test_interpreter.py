from studio.ingest import ingest_story
from studio.interpreter import interpret_story, source_hash
from studio.llm import LLMResponse, LLMRouter, LLMPolicy
from studio.adapters import AdapterInfo


class FakeInterpreter:
    info = AdapterInfo(
        id="test-interpreter",
        version="1",
        license="test-only",
        capabilities=("llm", "interpret", "local"),
        verified=True,
    )

    def generate(self, request):
        return LLMResponse(
            provider_id="test",
            model_id="test-model",
            model_version="1",
            text="structured",
            structured_output={
                "facts": [{"text": request.canonical_source}],
                "events": [{"id": "event-1", "description": "An explicit story event"}],
                "dialogue": [],
                "review_items": [],
            },
            provenance={"request_task": request.task},
        )

    def execute(self, request):
        return {"ok": True}


def test_interpretation_preserves_source_hash_and_provenance():
    story = ingest_story(story_id="s1", title="Test", text="Mara enters the forest.", source_kind="story")
    result = interpret_story(story, LLMRouter([FakeInterpreter()], LLMPolicy()))
    assert result.source_hash == source_hash(story)
    assert result.provenance["model_id"] == "test-model"
    assert result.events[0]["id"] == "event-1"
