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

STAGE_CAPABILITY = {
    "interpret": "story_interpretation", "plan_episode": "story_planning",
    "build_scenes": "storyboard", "build_shots": "storyboard",
    "resolve_assets": "asset_resolution", "animate": "animation",
    "dialogue": "voice", "lip_sync": "lip_sync", "sound_music": "music",
    "composite": "compositing", "edit": "editing", "master": "rendering", "qc": "qc",
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
    """Route production stages to verified adapters without requiring paid services.

    Adapters must expose ``is_local`` and may expose ``uses_paid_service`` or
    ``uses_paid_api``. Missing cost flags are treated conservatively as false,
    while the adapter still has to be explicitly verified.
    """

    def __init__(self, adapters: list[StageAdapter]):
        self.adapters = adapters

    def choose(self, capability: str) -> StageAdapter:
        for adapter in self.adapters:
            if capability not in adapter.info.capabilities or not adapter.info.verified:
                continue
            require_verified(adapter)
            require_zero_cost(
                is_local=bool(getattr(adapter, "is_local", True)),
                uses_paid_service=bool(getattr(adapter, "uses_paid_service", False)),
                uses_paid_api=bool(getattr(adapter, "uses_paid_api", False)),
            )
            return adapter
        raise RuntimeError(f"No verified zero-cost production adapter is available for capability: {capability}")

    def execute(self, request: ProductionRequest) -> ProductionResponse:
        capability = STAGE_CAPABILITY.get(request.stage, request.stage)
        adapter = self.choose(capability)
        response = adapter.execute(request)
        if not response.provenance:
            raise RuntimeError("production adapter returned no provenance")
        response.provenance.setdefault("cost_policy", "zero_recurring_cost")
        response.provenance.setdefault("execution_locality", "local" if bool(getattr(adapter, "is_local", True)) else "remote_free")
        return response
