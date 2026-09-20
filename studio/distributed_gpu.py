"""Atomic multi-worker GPU allocation and distributed rank planning.

This module is the control-plane layer between observed GPU hardware and a
distributed execution launcher. It never invents GPUs, network capability, or
NCCL readiness. Every allocation is bound to authenticated worker identity,
exact GPU UUIDs, observation digests, rank mapping, lease expiry, and a fencing
epoch.
"""
from __future__ import annotations

import itertools
import json
import secrets
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import sqlite3

from .gpu_infrastructure import GpuHostObservation
from .hardware_requirements import HardwareRequirements, compute_capability_at_least
from .nccl_evidence import validate_nccl_evidence
from .worker_registry import WorkerRecord, WorkerRegistry, WorkerState


class DistributedGpuAllocationState(StrEnum):
    RESERVED = "reserved"
    COMPLETED = "completed"
    RELEASED = "released"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class RankAssignment:
    global_rank: int
    node_rank: int
    local_rank: int
    worker_id: str
    gpu_uuid: str

    def __post_init__(self) -> None:
        if min(self.global_rank, self.node_rank, self.local_rank) < 0:
            raise ValueError("rank values cannot be negative")
        if not self.worker_id.strip() or not self.gpu_uuid.strip():
            raise ValueError("rank assignment requires worker and GPU identity")


@dataclass(frozen=True)
class DistributedNCCLEvidence:
    worker_ids: tuple[str, ...]
    gpu_uuids_by_worker: tuple[tuple[str, tuple[str, ...]], ...]
    world_size: int
    command: tuple[str, ...]
    exit_code: int
    output_sha256: str
    rendezvous_id: str
    topology_digests: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _sha256(self.output_sha256, "output_sha256")
        if len(self.worker_ids) < 2 or tuple(sorted(self.worker_ids)) != self.worker_ids:
            raise ValueError("distributed NCCL worker IDs must be sorted and contain at least two workers")
        if len({worker_id for worker_id in self.worker_ids}) != len(self.worker_ids):
            raise ValueError("distributed NCCL worker IDs must be unique")
        if not self.command:
            raise ValueError("distributed NCCL command is required")
        if self.exit_code != 0:
            raise ValueError("distributed NCCL evidence must have a successful exit code")
        if not self.rendezvous_id.strip():
            raise ValueError("distributed NCCL rendezvous identity is required")
        mapping = dict(self.gpu_uuids_by_worker)
        if tuple(sorted(mapping)) != self.worker_ids or len(mapping) != len(self.worker_ids):
            raise ValueError("distributed NCCL GPU mapping must exactly match worker IDs")
        if any(not gpus for gpus in mapping.values()):
            raise ValueError("distributed NCCL evidence must identify GPUs on every worker")
        if sum(len(gpus) for gpus in mapping.values()) != self.world_size:
            raise ValueError("distributed NCCL world size does not match GPU mapping")
        topology = dict(self.topology_digests)
        if tuple(sorted(topology)) != self.worker_ids:
            raise ValueError("distributed NCCL topology digests must exactly match worker IDs")
        for digest in topology.values():
            _sha256(digest, "topology digest")


@dataclass(frozen=True)
class GpuDirectNetworkEvidence:
    worker_pairs: tuple[tuple[str, str], ...]
    gpu_pairs: tuple[tuple[str, str], ...]
    transport: str
    command: tuple[str, ...]
    exit_code: int
    output_sha256: str

    def __post_init__(self) -> None:
        _sha256(self.output_sha256, "output_sha256")
        if not self.worker_pairs:
            raise ValueError("GPU-direct evidence must identify worker pairs")
        if any(left >= right for left, right in self.worker_pairs):
            raise ValueError("GPU-direct worker pairs must be canonical and ordered")
        if len(set(self.worker_pairs)) != len(self.worker_pairs):
            raise ValueError("GPU-direct worker pairs must be unique")
        if not self.gpu_pairs:
            raise ValueError("GPU-direct evidence must identify observed GPU peer pairs")
        if not self.transport.strip() or not self.command:
            raise ValueError("GPU-direct transport and command are required")
        if self.exit_code != 0:
            raise ValueError("GPU-direct evidence must have a successful exit code")


@dataclass(frozen=True)
class DistributedGpuPlan:
    task_id: str
    worker_ids: tuple[str, ...]
    gpus_by_worker: tuple[tuple[str, tuple[str, ...]], ...]
    world_size: int
    node_count: int
    hardware_observation_digests: tuple[tuple[str, str], ...]
    topology_digests: tuple[tuple[str, str], ...]

    @property
    def gpus_by_worker_map(self) -> dict[str, tuple[str, ...]]:
        return dict(self.gpus_by_worker)

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id is required")
        if len(self.worker_ids) < 2:
            raise ValueError("distributed plans require at least two workers")
        if tuple(sorted(self.worker_ids)) != self.worker_ids:
            raise ValueError("worker IDs must be sorted")
        mapping = self.gpus_by_worker_map
        if tuple(sorted(mapping)) != self.worker_ids:
            raise ValueError("GPU mapping must exactly match worker IDs")
        if any(not gpus for gpus in mapping.values()):
            raise ValueError("every distributed worker must receive at least one GPU")
        if sum(len(gpus) for gpus in mapping.values()) != self.world_size:
            raise ValueError("world size must equal the selected GPU count")
        if self.node_count != len(self.worker_ids):
            raise ValueError("node count must equal worker count")


@dataclass(frozen=True)
class DistributedGpuAllocation:
    allocation_id: str
    task_id: str
    worker_ids: tuple[str, ...]
    gpus_by_worker: tuple[tuple[str, tuple[str, ...]], ...]
    ranks: tuple[RankAssignment, ...]
    world_size: int
    node_count: int
    expires_at: int
    fencing_epoch: int
    hardware_observation_digests: tuple[tuple[str, str], ...]
    topology_digests: tuple[tuple[str, str], ...]
    state: DistributedGpuAllocationState = DistributedGpuAllocationState.RESERVED

    @property
    def gpus_by_worker_map(self) -> dict[str, tuple[str, ...]]:
        return dict(self.gpus_by_worker)


def _sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise ValueError(f"{field} must be a SHA-256 hex digest")


def _candidate_gpus(worker: WorkerRecord, requirements: HardwareRequirements, reserved: set[str]) -> tuple[str, ...]:
    observation = worker.hardware_observation
    if observation is None:
        return ()
    candidates = []
    for gpu in sorted(observation.gpus, key=lambda item: (item.index, item.uuid)):
        if gpu.uuid in reserved:
            continue
        if gpu.memory_total_mib * 1024**2 < requirements.min_vram_per_gpu_bytes:
            continue
        if requirements.min_compute_capability is not None:
            try:
                if not compute_capability_at_least(gpu.compute_capability, requirements.min_compute_capability):
                    continue
            except ValueError:
                continue
        if requirements.required_gpu_models and gpu.name not in requirements.required_gpu_models:
            continue
        candidates.append(gpu.uuid)
    return tuple(candidates)


class DistributedGpuAllocator:
    """Atomic distributed GPU reservation over the authenticated worker registry.

    The allocator is deliberately independent from the single-worker scheduler.
    A reservation succeeds only when all participating GPUs can be held at once.
    """

    _ACTIVE = {WorkerState.VERIFIED_AVAILABLE, WorkerState.VERIFIED_LIMITED}

    def __init__(self, registry: WorkerRegistry, store: "SQLiteDistributedGpuAllocationStore | None" = None):
        self.registry = registry
        self.store = store
        self._lock = threading.RLock()
        self._allocations: dict[str, DistributedGpuAllocation] = {}
        self._reserved: dict[tuple[str, str], str] = {}
        persisted = store.load() if store is not None else ()
        for allocation in persisted:
            self._allocations[allocation.allocation_id] = allocation
            if allocation.state is DistributedGpuAllocationState.RESERVED:
                for worker_id, gpus in allocation.gpus_by_worker:
                    for gpu_uuid in gpus:
                        self._reserved[(worker_id, gpu_uuid)] = allocation.allocation_id
        self._next_fencing_epoch = max((item.fencing_epoch for item in persisted), default=0) + 1

    def _available_workers(self, requirements: HardwareRequirements) -> list[tuple[str, tuple[str, ...]]]:
        result = []
        for worker in self.registry.snapshot():
            if worker.state not in self._ACTIVE or not worker.resource.healthy:
                continue
            candidates = _candidate_gpus(worker, requirements, {
                gpu_uuid for (worker_id, gpu_uuid) in self._reserved if worker_id == worker.id
            })
            if candidates:
                result.append((worker.id, candidates))
        return result

    def plan(self, task_id: str, requirements: HardwareRequirements, now: int, lease_seconds: int) -> DistributedGpuPlan:
        if not task_id.strip():
            raise ValueError("task_id is required")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        if requirements.placement.value != "multi_node":
            raise ValueError("distributed allocator requires MULTI_NODE placement")
        if not requirements.allow_multi_node:
            raise ValueError("multi-node allocation requires allow_multi_node=True")
        if requirements.min_gpu_count < 2:
            raise ValueError("multi-node allocation requires at least two GPUs")

        with self._lock:
            available = self._available_workers(requirements)
            if len(available) < 2:
                raise RuntimeError("distributed allocation requires at least two eligible workers")

            for node_count in range(2, len(available) + 1):
                for group in itertools.combinations(available, node_count):
                    total = sum(len(gpus) for _, gpus in group)
                    if total < requirements.min_gpu_count:
                        continue
                    selected: dict[str, tuple[str, ...]] = {}
                    remaining = requirements.min_gpu_count
                    for worker_id, gpus in group:
                        take = min(len(gpus), remaining)
                        selected[worker_id] = gpus[:take]
                        remaining -= take
                        if remaining == 0:
                            break
                    if remaining:
                        continue
                    if any(not gpus for gpus in selected.values()):
                        continue
                    worker_ids = tuple(sorted(selected))
                    selected = {worker_id: selected[worker_id] for worker_id in worker_ids}
                    observation_digests = []
                    topology_digests = []
                    for worker_id in worker_ids:
                        observation = self.registry.get(worker_id).hardware_observation
                        if observation is None:
                            break
                        observation_digests.append((worker_id, observation.digest()))
                        if observation.topology_evidence is None:
                            if requirements.require_nccl:
                                break
                        else:
                            topology_digests.append((worker_id, observation.topology_evidence.raw_text_sha256))
                        if requirements.require_nccl:
                            if observation.nccl_evidence is None:
                                break
                            try:
                                validate_nccl_evidence(observation.nccl_evidence)
                            except (ValueError, RuntimeError):
                                break
                            if tuple(observation.nccl_evidence.gpu_uuids) != selected[worker_id]:
                                break
                    else:
                        total_vram = sum(
                            next(gpu for gpu in self.registry.get(worker_id).hardware_observation.gpus if gpu.uuid == gpu_uuid).memory_total_mib * 1024**2
                            for worker_id, gpus in selected.items()
                            for gpu_uuid in gpus
                        )
                        if total_vram < requirements.min_total_vram_bytes:
                            continue
                        return DistributedGpuPlan(
                            task_id=task_id,
                            worker_ids=worker_ids,
                            gpus_by_worker=tuple((worker_id, selected[worker_id]) for worker_id in worker_ids),
                            world_size=requirements.min_gpu_count,
                            node_count=len(worker_ids),
                            hardware_observation_digests=tuple(observation_digests),
                            topology_digests=tuple(topology_digests),
                        )
            raise RuntimeError("no eligible multi-node GPU group satisfies the observed hardware requirements")

    def try_reserve(self, task_id: str, requirements: HardwareRequirements, now: int, lease_seconds: int, **evidence):
        try:
            return self.reserve(task_id, requirements, now, lease_seconds, **evidence)
        except RuntimeError:
            return None

    def reserve(
        self,
        task_id: str,
        requirements: HardwareRequirements,
        now: int,
        lease_seconds: int,
        *,
        distributed_nccl: DistributedNCCLEvidence | None = None,
        gpu_direct_network: GpuDirectNetworkEvidence | None = None,
    ) -> DistributedGpuAllocation:
        with self._lock:
            plan = self.plan(task_id, requirements, now, lease_seconds)
            if requirements.require_nccl:
                self._validate_distributed_nccl(plan, distributed_nccl)
            if requirements.require_gpu_direct_network:
                self._validate_gpu_direct(plan, gpu_direct_network)

            allocation_id = "alloc-" + secrets.token_hex(16)
            epoch = self._next_fencing_epoch
            self._next_fencing_epoch += 1
            ranks = []
            global_rank = 0
            for node_rank, worker_id in enumerate(plan.worker_ids):
                for local_rank, gpu_uuid in enumerate(dict(plan.gpus_by_worker)[worker_id]):
                    ranks.append(RankAssignment(global_rank, node_rank, local_rank, worker_id, gpu_uuid))
                    global_rank += 1

            allocation = DistributedGpuAllocation(
                allocation_id=allocation_id,
                task_id=task_id,
                worker_ids=plan.worker_ids,
                gpus_by_worker=plan.gpus_by_worker,
                ranks=tuple(ranks),
                world_size=plan.world_size,
                node_count=plan.node_count,
                expires_at=now + lease_seconds,
                fencing_epoch=epoch,
                hardware_observation_digests=plan.hardware_observation_digests,
                topology_digests=plan.topology_digests,
            )
            for worker_id, gpus in plan.gpus_by_worker:
                for gpu_uuid in gpus:
                    key = (worker_id, gpu_uuid)
                    if key in self._reserved:
                        raise RuntimeError("GPU became reserved while allocation was being committed")
            if self.store is not None:
                self.store.reserve(allocation)
            for worker_id, gpus in plan.gpus_by_worker:
                for gpu_uuid in gpus:
                    self._reserved[(worker_id, gpu_uuid)] = allocation_id
            self._allocations[allocation_id] = allocation
            return allocation

    def _validate_distributed_nccl(self, plan: DistributedGpuPlan, evidence: DistributedNCCLEvidence | None) -> None:
        if evidence is None:
            raise RuntimeError("distributed NCCL evidence is required")
        expected = plan.gpus_by_worker
        if evidence.worker_ids != plan.worker_ids or evidence.gpu_uuids_by_worker != expected:
            raise RuntimeError("distributed NCCL evidence does not match the exact planned GPUs")
        if evidence.world_size != plan.world_size:
            raise RuntimeError("distributed NCCL evidence world size does not match allocation")
        if evidence.topology_digests != plan.topology_digests:
            raise RuntimeError("distributed NCCL topology evidence does not match observed topology")
        if evidence.exit_code != 0:
            raise RuntimeError("distributed NCCL evidence is not successful")

    def _validate_gpu_direct(self, plan: DistributedGpuPlan, evidence: GpuDirectNetworkEvidence | None) -> None:
        if evidence is None:
            raise RuntimeError("GPU-direct network evidence is required")
        required_pairs = set(itertools.combinations(plan.worker_ids, 2))
        if not required_pairs.issubset(set(evidence.worker_pairs)):
            raise RuntimeError("GPU-direct evidence does not cover every selected worker pair")
        selected_gpus = {gpu_uuid for _, gpus in plan.gpus_by_worker for gpu_uuid in gpus}
        if any(left not in selected_gpus or right not in selected_gpus for left, right in evidence.gpu_pairs):
            raise RuntimeError("GPU-direct evidence references GPUs outside the exact allocation")
        if evidence.exit_code != 0:
            raise RuntimeError("GPU-direct network evidence is not successful")

    def get(self, allocation_id: str) -> DistributedGpuAllocation:
        with self._lock:
            try:
                return self._allocations[allocation_id]
            except KeyError as exc:
                raise KeyError(f"unknown distributed allocation: {allocation_id}") from exc

    def _transition(self, allocation_id: str, fencing_epoch: int, state: DistributedGpuAllocationState, now: int) -> None:
        allocation = self.get(allocation_id)
        if allocation.fencing_epoch != fencing_epoch:
            raise PermissionError("fencing epoch does not match current allocation")
        if allocation.state is not DistributedGpuAllocationState.RESERVED:
            raise RuntimeError("distributed allocation is no longer active")
        if now >= allocation.expires_at and state is not DistributedGpuAllocationState.EXPIRED:
            raise RuntimeError("distributed allocation lease has expired")
        updated = DistributedGpuAllocation(
            **{**allocation.__dict__, "state": state}
        )
        self._allocations[allocation_id] = updated
        if self.store is not None:
            self.store.update(updated)
        for worker_id, gpus in allocation.gpus_by_worker:
            for gpu_uuid in gpus:
                self._reserved.pop((worker_id, gpu_uuid), None)

    def complete(self, allocation_id: str, fencing_epoch: int, now: int) -> None:
        with self._lock:
            self._transition(allocation_id, fencing_epoch, DistributedGpuAllocationState.COMPLETED, now)

    def release(self, allocation_id: str, fencing_epoch: int, now: int) -> None:
        with self._lock:
            self._transition(allocation_id, fencing_epoch, DistributedGpuAllocationState.RELEASED, now)

    def fail(self, allocation_id: str, fencing_epoch: int, now: int) -> None:
        with self._lock:
            self._transition(allocation_id, fencing_epoch, DistributedGpuAllocationState.FAILED, now)

    def expire(self, now: int) -> tuple[str, ...]:
        expired = []
        with self._lock:
            for allocation in tuple(self._allocations.values()):
                if allocation.state is DistributedGpuAllocationState.RESERVED and allocation.expires_at <= now:
                    self._transition(allocation.allocation_id, allocation.fencing_epoch, DistributedGpuAllocationState.EXPIRED, now)
                    expired.append(allocation.allocation_id)
        return tuple(sorted(expired))


class SQLiteDistributedGpuAllocationStore:
    """Durable cross-process reservation store.

    The unique worker/GPU reservation key is the concurrency boundary. A
    transaction either records the entire allocation and every GPU reservation,
    or records none of it.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS distributed_allocations (allocation_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS distributed_gpu_reservations (worker_id TEXT NOT NULL, gpu_uuid TEXT NOT NULL, allocation_id TEXT NOT NULL, PRIMARY KEY(worker_id, gpu_uuid), FOREIGN KEY(allocation_id) REFERENCES distributed_allocations(allocation_id))"
            )

    def load(self) -> tuple[DistributedGpuAllocation, ...]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT payload FROM distributed_allocations ORDER BY allocation_id"
            ).fetchall()
        return tuple(_allocation_from_json(json.loads(payload)) for (payload,) in rows)

    def reserve(self, allocation: DistributedGpuAllocation) -> None:
        payload = json.dumps(_allocation_json(allocation), sort_keys=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO distributed_allocations(allocation_id,payload) VALUES (?,?)",
                    (allocation.allocation_id, payload),
                )
                connection.executemany(
                    "INSERT INTO distributed_gpu_reservations(worker_id,gpu_uuid,allocation_id) VALUES (?,?,?)",
                    [
                        (worker_id, gpu_uuid, allocation.allocation_id)
                        for worker_id, gpus in allocation.gpus_by_worker
                        for gpu_uuid in gpus
                    ],
                )
            except sqlite3.IntegrityError as exc:
                raise RuntimeError("distributed GPU reservation conflicts with an existing allocation") from exc

    def update(self, allocation: DistributedGpuAllocation) -> None:
        payload = json.dumps(_allocation_json(allocation), sort_keys=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE distributed_allocations SET payload = ? WHERE allocation_id = ?",
                (payload, allocation.allocation_id),
            )
            if allocation.state is not DistributedGpuAllocationState.RESERVED:
                connection.execute(
                    "DELETE FROM distributed_gpu_reservations WHERE allocation_id = ?",
                    (allocation.allocation_id,),
                )


def _allocation_from_json(payload: dict) -> DistributedGpuAllocation:
    return DistributedGpuAllocation(
        allocation_id=payload["allocation_id"],
        task_id=payload["task_id"],
        worker_ids=tuple(payload["worker_ids"]),
        gpus_by_worker=tuple((worker_id, tuple(gpus)) for worker_id, gpus in payload["gpus_by_worker"]),
        ranks=tuple(RankAssignment(**item) for item in payload["ranks"]),
        world_size=payload["world_size"],
        node_count=payload["node_count"],
        expires_at=payload["expires_at"],
        fencing_epoch=payload["fencing_epoch"],
        hardware_observation_digests=tuple(
            (worker_id, digest) for worker_id, digest in payload["hardware_observation_digests"]
        ),
        topology_digests=tuple(
            (worker_id, digest) for worker_id, digest in payload["topology_digests"]
        ),
        state=DistributedGpuAllocationState(payload["state"]),
    )


def _allocation_json(allocation: DistributedGpuAllocation) -> dict:
    return {
        "allocation_id": allocation.allocation_id,
        "task_id": allocation.task_id,
        "worker_ids": list(allocation.worker_ids),
        "gpus_by_worker": [[worker_id, list(gpus)] for worker_id, gpus in allocation.gpus_by_worker],
        "ranks": [rank.__dict__ for rank in allocation.ranks],
        "world_size": allocation.world_size,
        "node_count": allocation.node_count,
        "expires_at": allocation.expires_at,
        "fencing_epoch": allocation.fencing_epoch,
        "hardware_observation_digests": [list(item) for item in allocation.hardware_observation_digests],
        "topology_digests": [list(item) for item in allocation.topology_digests],
        "state": allocation.state.value,
    }
