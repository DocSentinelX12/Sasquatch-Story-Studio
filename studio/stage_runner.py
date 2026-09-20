"""Bridge pipeline stages to real verified production adapters and workers."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .compute_broker import ProductionTask
from .distributed_execution import DistributedLaunchSpec
from .pipeline import RunState
from .production import ProductionRequest, ProductionRouter
from .scheduler import JobRequirements
from .worker import WorkerTask
from .worker_fabric import DispatchState, WorkerFabric


class RoutedStageRunner:
    """Direct adapter runner retained for single-worker/local operation."""

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


@dataclass(frozen=True)
class DistributedStageRunner:
    """Create typed broker tasks and dispatch them through the worker fabric."""

    fabric: WorkerFabric
    canonical_source_hash: str
    episode_id: str
    shot_id: str
    distributed_launch_spec: DistributedLaunchSpec | None = None

    def run_stage(
        self,
        *,
        stage: str,
        payload: dict[str, Any],
        requirements: JobRequirements,
        input_refs: tuple[str, ...] = (),
        input_hashes: tuple[str, ...] = (),
        priority: int = 0,
        now: int,
        task_id: str,
    ) -> str:
        if len(input_refs) != len(input_hashes):
            raise ValueError("input references and hashes must have equal lengths")
        if len(self.canonical_source_hash) != 64:
            raise ValueError("canonical_source_hash must be a SHA-256 hex digest")
        production_task = ProductionTask(task_id, requirements, priority)
        hardware = requirements.hardware
        if hardware is not None and hardware.placement.value == "multi_node":
            if self.distributed_launch_spec is None:
                raise RuntimeError(
                    "MULTI_NODE stage requires an explicit verified distributed launch specification"
                )
            record = self.fabric.dispatch_distributed(
                production_task,
                self.distributed_launch_spec,
                now=now,
            )
            if record.state != DispatchState.COMPLETED or not record.output_refs:
                raise RuntimeError(record.error or f"distributed stage {stage} did not complete")
            return record.output_refs[0]

        self.fabric.broker.submit(production_task)

        def factory(task: ProductionTask, job, worker_id: str) -> WorkerTask:
            return WorkerTask(
                task_id=task.id,
                episode_id=self.episode_id,
                stage=stage,
                shot_id=self.shot_id,
                input_refs=input_refs,
                input_hashes=input_hashes,
                requirements=requirements,
                provenance_context=(("worker_id", worker_id), ("gpu_uuids", ",".join(job.allocated_gpu_uuids))),
                canonical_source_hash=self.canonical_source_hash,
                payload_json=json.dumps(payload, sort_keys=True),
                gpu_uuids=job.allocated_gpu_uuids,
            )

        record = self.fabric.dispatch(production_task, factory, now=now)
        if record.state != DispatchState.COMPLETED or not record.output_refs:
            raise RuntimeError(record.error or f"stage {stage} did not complete")
        return record.output_refs[0]
