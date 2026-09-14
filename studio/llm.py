"""LLM abstraction and safety policy for story-faithful production intelligence.

LLMs are production assistants, never the creative source of truth. Providers are
adapters so local/open models can be swapped without changing canonical story data.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from .adapters import AdapterInfo, ProductionAdapter, require_verified
from .cost_policy import require_local_zero_cost


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

    def validate(self, max_temperature: float = 0.7) -> None:
        if not self.task.strip():
            raise ValueError("LLM task is required")
        if not self.system_instruction.strip():
            raise ValueError("LLM system instruction is required")
        if not self.user_input.strip():
            raise ValueError("LLM user input is required")
        if not self.canonical_source.strip():
            raise ValueError("canonical source is required")
        if self.temperature < 0 or self.temperature > max_temperature:
            raise ValueError(f"temperature must be between 0 and {max_temperature}")
        if self.canonical_source != self.user_input:
            raise ValueError("canonical_source must exactly match user_input for protected story tasks")
        if self.output_schema is not None and self.output_schema.get("type") not in (None, "object"):
            raise ValueError("production LLM structured output schemas must have an object root")


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
    allow_paid_api: bool = False
    max_temperature: float = 0.7

    def __post_init__(self) -> None:
        if self.allow_paid_api:
            raise ValueError("paid LLM APIs are prohibited by the studio zero-recurring-cost policy")
        if self.allow_remote:
            raise ValueError("remote LLM execution is prohibited by the studio local-only production policy")


class LLMRouter:
    """Select only verified, local, policy-eligible LLM adapters."""

    def __init__(self, adapters: list[LLMAdapter], policy: LLMPolicy | None = None):
        self.adapters = adapters
        self.policy = policy or LLMPolicy()

    def eligible(self, task: str) -> list[LLMAdapter]:
        candidates: list[LLMAdapter] = []
        for adapter in self.adapters:
            if self.policy.require_verified and not adapter.info.verified:
                continue
            if not self.policy.allow_unknown_license and not adapter.info.license.strip():
                continue
            is_local = "local" in adapter.info.capabilities
            if not self.policy.allow_remote and not is_local:
                continue
            if task in adapter.info.capabilities or "llm" in adapter.info.capabilities:
                candidates.append(adapter)
        return candidates

    def choose(self, task: str) -> LLMAdapter:
        candidates = self.eligible(task)
        if not candidates:
            raise RuntimeError(f"No policy-eligible verified local LLM adapter is available for task: {task}")
        if self.policy.prefer_local:
            local = [a for a in candidates if "local" in a.info.capabilities]
            if local:
                require_local_zero_cost(is_local=True, uses_paid_api=False)
                return local[0]
        raise RuntimeError("Zero-cost policy requires a local LLM adapter")

    def generate(self, request: LLMRequest) -> LLMResponse:
        request.validate(self.policy.max_temperature)
        adapter = self.choose(request.task)
        response = adapter.generate(request)
        if not response.provenance:
            raise RuntimeError("LLM adapter returned no provenance")
        response.provenance.setdefault("cost_policy", "zero_recurring_cost_local_only")
        return response


CANONICAL_LLM_INSTRUCTION = (
    "The creator's supplied story and explicit production instructions are canonical. "
    "Extract, organize, and production-plan that material. Do not silently invent, "
    "remove, change, or reorder story events, dialogue, characters, outcomes, or "
    "meaning. If a production decision requires creative invention, record it as a "
    "review item instead of presenting it as creator canon."
)
