"""LLM abstraction and safety policy for story-faithful production intelligence.

LLMs are production assistants, never the creative source of truth. Providers are
adapters so local/open models can be swapped without changing canonical story data.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from .adapters import AdapterInfo, ProductionAdapter, require_verified


@dataclass(frozen=True)
class LLMRequest:
    task: str
    system_instruction: str
    user_input: str
    canonical_source: str
    output_schema: dict[str, Any] | None = None
    temperature: float = 0.0
    seed: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    provider_id: str
    model_id: str
    model_version: str
    text: str
    structured_output: dict[str, Any] | None
    provenance: dict[str, Any]


class LLMAdapter(ProductionAdapter, Protocol):
    info: AdapterInfo

    def generate(self, request: LLMRequest) -> LLMResponse:
        ...


@dataclass(frozen=True)
class LLMPolicy:
    require_verified: bool = True
    prefer_local: bool = True
    allow_remote: bool = False
    allow_unknown_license: bool = False
    max_temperature: float = 0.7


class LLMRouter:
    """Selects only verified LLM adapters and records the routing decision."""

    def __init__(self, adapters: list[LLMAdapter], policy: LLMPolicy | None = None):
        self.adapters = adapters
        self.policy = policy or LLMPolicy()

    def eligible(self, task: str) -> list[LLMAdapter]:
        candidates = []
        for adapter in self.adapters:
            if self.policy.require_verified:
                require_verified(adapter)
            if task in adapter.info.capabilities or "llm" in adapter.info.capabilities:
                candidates.append(adapter)
        return candidates

    def choose(self, task: str) -> LLMAdapter:
        candidates = self.eligible(task)
        if not candidates:
            raise RuntimeError(f"No verified LLM adapter is available for task: {task}")
        if self.policy.prefer_local:
            local = [a for a in candidates if "local" in a.info.capabilities]
            if local:
                return local[0]
        return candidates[0]


CANONICAL_LLM_INSTRUCTION = (
    "The creator's supplied story and explicit production instructions are canonical. "
    "Extract, organize, and production-plan that material. Do not silently invent, "
    "remove, change, or reorder story events, dialogue, characters, outcomes, or "
    "meaning. If a production decision requires creative invention, record it as a "
    "review item instead of presenting it as creator canon."
)
