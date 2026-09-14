"""Model-agnostic production adapter contracts and stage orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .adapters import AdapterInfo, ProductionAdapter, require_verified
from .cost_policy import require_zero_cost

PRODUCTION_CAPABILITIES = (
    "story_interpretation", "story_planning", "storyboard", "asset_resolution",
    "image_generation", "video_generation", "animation", "voice", "lip_sync",
    "music", "sfx", "compositing", "editing", "rendering", "qc",
)

# A tuple means the stage can be fulfilled by any of the listed capabilities.
# This is important for video-generation engines such as Wan/LTX/ComfyUI: they
# are valid animation backends even when they do not label themselves "animation".
STAGE_CAPABILITY: dict[str, str | tuple[str, ...]] = {
    "interpret": "story_interpretation",
    "plan_episode": "story_planning",
    "build_scenes": "storyboard",
    "build_shots": "storyboard",
    "resolve_assets": ("asset_resolution", "image_generation"),
    "animate": ("animation", "video_generation"),
    "dialogue": "voice",
    "lip_sync": "lip_sync",
    "sound_music": ("music", "sfx"),
    "composite": "compositing",
    "edit": "editing",
    "master": "rendering",
    "qc": "qc",
}

_QUALITY_RANK = {
    "very_high": 5,
    "high": 4,
    "professional_2d": 4,
    "professional_3d": 4,
    "production_tts": 4,
    "generic": 0,
}


@dataclass(frozen=True)
class ProductionRequest:
    stage: str
    payload: dict[str, Any]
    canonical_source_hash: str
    parameters: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None


@dataclass(frozen=True)
class ProductionResponse:
    adapter_id: str
    output_refs: tuple[str, ...]
    provenance: dict[str, Any]


class StageAdapter(ProductionAdapter, Protocol):
    info: AdapterInfo

    def execute(self, request: ProductionRequest) -> ProductionResponse:
        ...


class ProductionRouter:
    """Route production stages to verified zero-recurring-cost adapters.

    Selection is capability-aware and quality-first. Engines whose commercial
    license status still requires review are not selected unless explicitly
    enabled by the caller.
    """

    def __init__(self, adapters: list[StageAdapter], *, allow_commercial_review_required: bool = False):
        self.adapters = adapters
        self.allow_commercial_review_required = allow_commercial_review_required

    def choose(self, capability: str | tuple[str, ...]) -> StageAdapter:
        required = (capability,) if isinstance(capability, str) else capability
        candidates: list[StageAdapter] = []
        for adapter in self.adapters:
            if not adapter.info.verified:
                continue
            if not any(item in adapter.info.capabilities for item in required):
                continue
            if (
                bool(getattr(adapter, "commercial_use_review_required", False))
                and not self.allow_commercial_review_required
            ):
                continue
            require_verified(adapter)
            require_zero_cost(
                is_local=bool(getattr(adapter, "is_local", True)),
                uses_paid_service=bool(getattr(adapter, "uses_paid_service", False)),
                uses_paid_api=bool(getattr(adapter, "uses_paid_api", False)),
            )
            candidates.append(adapter)

        if not candidates:
            labels = ", ".join(required)
            raise RuntimeError(f"No verified zero-cost production adapter is available for capability: {labels}")

        return max(
            candidates,
            key=lambda adapter: (
                _QUALITY_RANK.get(str(getattr(adapter, "quality_tier", "generic")), 0),
                adapter.info.id,
            ),
        )

    def execute(self, request: ProductionRequest) -> ProductionResponse:
        capability = STAGE_CAPABILITY.get(request.stage, request.stage)
        adapter = self.choose(capability)
        response = adapter.execute(request)
        if not response.provenance:
            raise RuntimeError("production adapter returned no provenance")
        response.provenance.setdefault("cost_policy", "zero_recurring_cost")
        response.provenance.setdefault(
            "execution_locality",
            "local" if bool(getattr(adapter, "is_local", True)) else "remote_free",
        )
        return response
