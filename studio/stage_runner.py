"""Bridge pipeline stages to real verified production adapters."""
from __future__ import annotations
from typing import Any
from .pipeline import RunState
from .production import ProductionRequest, ProductionRouter

class RoutedStageRunner:
    def __init__(self, router: ProductionRouter, canonical_source_hash: str, payloads: dict[str, dict[str, Any]]):
        self.router = router
        self.canonical_source_hash = canonical_source_hash
        self.payloads = payloads

    def handler(self, stage: str):
        def run(state: RunState) -> str:
            payload = self.payloads.get(stage)
            if payload is None:
                raise RuntimeError(f"No production payload supplied for stage: {stage}")
            response = self.router.execute(ProductionRequest(stage=stage, payload=payload, canonical_source_hash=self.canonical_source_hash, seed=payload.get("seed")))
            if not response.output_refs:
                raise RuntimeError(f"Verified adapter {response.adapter_id} produced no output references for {stage}")
            return response.output_refs[0]
        return run

    def handlers(self, stages: tuple[str, ...]) -> dict[str, Any]:
        return {stage: self.handler(stage) for stage in stages}
