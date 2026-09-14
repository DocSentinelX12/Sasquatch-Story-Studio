"""Real production adapter execution as a worker-fabric executor."""
from __future__ import annotations

import json
from dataclasses import dataclass

from .adapters import ProductionAdapter, require_verified
from .artifact_bridge import ArtifactCommitter
from .production import ProductionRequest
from .worker import WorkerResult, WorkerResultState, WorkerTask


@dataclass(frozen=True)
class ProductionWorkerExecutor:
    """Execute one verified adapter and commit its real outputs to CAS."""

    adapter: ProductionAdapter
    artifact_committer: ArtifactCommitter

    def execute(self, task: WorkerTask) -> WorkerResult:
        if not task.canonical_source_hash or not task.payload_json:
            return WorkerResult(task.task_id, WorkerResultState.REJECTED, error="worker task lacks canonical production request data")
        try:
            require_verified(self.adapter)
            payload = json.loads(task.payload_json)
            if not isinstance(payload, dict):
                raise ValueError("production payload must decode to an object")
            requested_engine = payload.get("engine_id")
            if requested_engine and requested_engine != self.adapter.info.id:
                raise RuntimeError(f"worker adapter {self.adapter.info.id} does not match requested engine {requested_engine}")
            request = ProductionRequest(
                stage=task.stage,
                payload=payload,
                canonical_source_hash=task.canonical_source_hash,
                parameters=payload.get("parameters", {}) if isinstance(payload.get("parameters", {}), dict) else {},
                seed=payload.get("seed"),
            )
            response = self.adapter.execute(request)
            output_refs = self.artifact_committer.commit(response, stage=task.stage, source_hash=task.canonical_source_hash)
            return WorkerResult(task.task_id, WorkerResultState.COMPLETED, output_refs=output_refs)
        except (RuntimeError, ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
            return WorkerResult(task.task_id, WorkerResultState.FAILED, error=str(exc))
