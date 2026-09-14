"""Evidence-gated runtime execution boundary."""
from dataclasses import dataclass
from typing import Any

from .adapters import ProductionAdapter, require_verified
from .compute_broker import ComputeBroker, ProductionTask
from .engine_registry import assert_verified_engine
from .worker import WorkerTask


@dataclass(frozen=True)
class RuntimeExecutionResult:
    task_id: str
    engine_id: str
    worker_id: str
    output_refs: tuple[str, ...]
    provenance: dict[str, Any]


class RuntimeExecutionCoordinator:
    def __init__(self, broker: ComputeBroker) -> None:
        self.broker = broker

    def execute(self, *, engine_id: str, adapter: ProductionAdapter, task: ProductionTask, worker_task: WorkerTask, request: dict[str, Any]) -> RuntimeExecutionResult:
        assert_verified_engine(engine_id)
        require_verified(adapter)
        if adapter.info.id != engine_id:
            raise ValueError("Adapter identity does not match verified engine")
        if task.task_id != worker_task.task_id:
            raise ValueError("Production and worker task IDs must match")
        worker = self.broker.lease(task)
        if worker is None:
            raise RuntimeError(f"No eligible worker for task {task.task_id}")
        try:
            response = adapter.execute(request)
            refs = tuple(response.get("output_refs", ()))
            if not refs:
                raise RuntimeError("Verified engine produced no output references")
            provenance = dict(response.get("provenance", {}))
            provenance.update({"task_id": task.task_id, "worker_id": worker.worker_id, "engine_id": engine_id})
            self.broker.release_or_requeue(task.task_id, completed=True)
            return RuntimeExecutionResult(task.task_id, engine_id, worker.worker_id, refs, provenance)
        except Exception:
            self.broker.release_or_requeue(task.task_id, completed=False)
            raise
