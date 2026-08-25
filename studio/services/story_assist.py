"""Story assistance hooks (PART 16).

These functions are the single integration point for future AI story
providers. They NEVER fabricate output: if no provider is configured they
raise ProviderNotConfigured, and the API surfaces an honest error. Manual
writing in the UI never depends on them.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..providers.registry import DEFINITIONS, AdapterNotImplemented, ProviderNotConfigured

ASSIST_TASKS = (
    "generate_ideas",       # brainstorm story ideas from a seed
    "expand_story",         # idea → premise/logline/beats
    "generate_outline",     # beats → scene-by-scene outline
    "improve_dialogue",     # polish a dialogue exchange
    "scene_description",    # scene summary/action/visual direction draft
    "shot_suggestions",     # suggested shot list for a scene (Phase 4 prep)
)


@dataclass(frozen=True)
class AssistRequest:
    task: str
    input_text: str
    context: dict            # story/episode/scene ids, bible + canon context


@dataclass(frozen=True)
class AssistResult:
    task: str
    provider: str
    output: str


def story_providers() -> list[dict]:
    return [
        {"key": d.key, "display_name": d.display_name, "status": d.status(),
         "missing_env": d.missing_env()}
        for d in DEFINITIONS.values() if d.kind == "story"
    ]


def run_assist(request: AssistRequest, provider_key: str | None = None) -> AssistResult:
    """Execute a story-assistance task through a configured provider.

    In Phase 3 no text adapter exists, so this honestly refuses:
    - no credentials  → ProviderNotConfigured (409 at the API)
    - credentials set → AdapterNotImplemented (501 at the API)
    Manual editing is never blocked either way.
    """
    candidates = [d for d in DEFINITIONS.values() if d.kind == "story"]
    definition = next((d for d in candidates if d.key == provider_key), None)
    if definition is None:
        # no specific provider: require exactly one configured candidate
        configured = [d for d in candidates if not d.missing_env()]
        if len(configured) == 1:
            definition = configured[0]
        else:
            missing = {d.key: d.missing_env() for d in candidates}
            raise ProviderNotConfigured(
                "story-assistance", sorted({m for v in missing.values() for m in v})
            )
    missing = definition.missing_env()
    if missing:
        raise ProviderNotConfigured(definition.key, missing)
    raise AdapterNotImplemented(definition.key)
