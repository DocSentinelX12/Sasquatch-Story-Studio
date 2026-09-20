"""Authenticated remote worker execution contracts.

The module keeps production state authoritative on the control plane. A remote
worker receives only an already leased production task and its exact GPU
allocation. Enrollment credentials are provisioned outside source control.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .data_plane import DataPlane, TransferPlan
from .distributed_gpu import DistributedGpuAllocation, DistributedGpuAllocationState, RankAssignment
from .hardware_requirements import HardwareRequirements
from .scheduler import JobRequirements
from .worker import WorkerResult, WorkerResultState, WorkerTask


@dataclass(frozen=True)
class RemoteLease:
    lease_id: str
    task_id: str
    worker_id: str
    expires_at: int
    gpu_uuids: tuple[str, ...]
    execution_nonce: str

    def __post_init__(self) -> None:
        if not self.lease_id.strip() or not self.task_id.strip() or not self.worker_id.strip():
            raise ValueError("remote lease identity is required")
        if self.expires_at < 0:
            raise ValueError("lease expiry cannot be negative")
        if len(set(self.gpu_uuids)) != len(self.gpu_uuids):
            raise ValueError("remote lease GPU allocation cannot contain duplicates")
        if not self.execution_nonce.strip():
            raise ValueError("execution nonce is required")


@dataclass(frozen=True)
class DistributedWorkerLease:
    allocation_id: str
    task_id: str
    worker_id: str
    world_size: int
    node_count: int
    node_rank: int
    ranks: tuple[RankAssignment, ...]
    gpu_uuids: tuple[str, ...]
    expires_at: int
    fencing_epoch: int
    execution_nonce: str

    def __post_init__(self) -> None:
        if not self.allocation_id.strip() or not self.task_id.strip() or not self.worker_id.strip():
            raise ValueError("distributed lease identity is required")
        if self.world_size < 2 or self.node_count < 2:
            raise ValueError("distributed lease must represent a multi-node allocation")
        if self.node_rank < 0 or self.node_rank >= self.node_count:
            raise ValueError("distributed lease node rank is invalid")
        if self.expires_at < 0 or self.fencing_epoch < 1:
            raise ValueError("distributed lease expiry and fencing epoch must be valid")
        if not self.execution_nonce.strip():
            raise ValueError("distributed lease execution nonce is required")
        if len(set(self.gpu_uuids)) != len(self.gpu_uuids):
            raise ValueError("distributed lease GPU allocation cannot contain duplicates")
        rank_gpus = tuple(rank.gpu_uuid for rank in self.ranks)
        if rank_gpus != self.gpu_uuids:
            raise ValueError("distributed lease ranks must exactly match its GPU allocation")
        if any(rank.worker_id != self.worker_id or rank.node_rank != self.node_rank for rank in self.ranks):
            raise ValueError("distributed lease rank ownership does not match worker identity")
        if any(rank.global_rank < 0 or rank.local_rank < 0 for rank in self.ranks):
            raise ValueError("distributed lease ranks must be non-negative")


@dataclass(frozen=True)
class WorkerAccess:
    worker_id: str
    access_token: str

    def __post_init__(self) -> None:
        if not self.worker_id.strip() or not self.access_token.strip():
            raise ValueError("worker access requires worker_id and access token")


class RemoteWorkerTransport(Protocol):
    def post_json(self, path: str, payload: Mapping[str, Any], *, bearer_token: str) -> dict[str, Any]:
        ...

    def get_bytes(self, path: str, *, bearer_token: str, expected_digest: str, offset: int, size_bytes: int) -> bytes:
        ...


def _hardware_payload(requirements: HardwareRequirements | None) -> dict[str, Any] | None:
    if requirements is None:
        return None
    return {
        "min_gpu_count": requirements.min_gpu_count,
        "min_vram_per_gpu_bytes": requirements.min_vram_per_gpu_bytes,
        "min_total_vram_bytes": requirements.min_total_vram_bytes,
        "min_compute_capability": requirements.min_compute_capability,
        "required_gpu_models": requirements.required_gpu_models,
        "placement": requirements.placement.value,
        "require_nccl": requirements.require_nccl,
        "allow_multi_node": requirements.allow_multi_node,
        "require_gpu_direct_network": requirements.require_gpu_direct_network,
    }


def _requirements_payload(requirements: object) -> dict[str, Any]:
    if not isinstance(requirements, JobRequirements):
        raise ValueError("remote worker task requirements must be JobRequirements")
    return {
        "slots": requirements.slots,
        "memory_bytes": requirements.memory_bytes,
        "vram_bytes": requirements.vram_bytes,
        "scratch_bytes": requirements.scratch_bytes,
        "power_watts": requirements.power_watts,
        "capabilities": requirements.capabilities,
        "engines": requirements.engines,
        "hardware": _hardware_payload(requirements.hardware),
    }


def _task_payload(task: WorkerTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "episode_id": task.episode_id,
        "stage": task.stage,
        "shot_id": task.shot_id,
        "input_refs": task.input_refs,
        "input_hashes": task.input_hashes,
        "requirements": _requirements_payload(task.requirements),
        "provenance_context": task.provenance_context,
        "canonical_source_hash": task.canonical_source_hash,
        "payload_json": task.payload_json,
        "gpu_uuids": task.gpu_uuids,
    }


class RemoteWorkerExecutor:
    """Network-backed executor that requires a control-plane lease."""

    def __init__(self, transport: RemoteWorkerTransport, access: WorkerAccess):
        self.transport = transport
        self.access = access

    def execute_with_lease(self, task: WorkerTask, lease: RemoteLease) -> WorkerResult:
        if lease.worker_id != self.access.worker_id or lease.task_id != task.task_id:
            return WorkerResult(task.task_id, WorkerResultState.REJECTED, error="remote lease does not match worker task")
        if lease.gpu_uuids != task.gpu_uuids:
            return WorkerResult(task.task_id, WorkerResultState.REJECTED, error="remote lease GPU allocation does not match worker task")
        response = self.transport.post_json(
            "/v1/worker/execute",
            {"lease": lease.__dict__, "task": _task_payload(task)},
            bearer_token=self.access.access_token,
        )
        state = response.get("state")
        if state not in {item.value for item in WorkerResultState}:
            raise RuntimeError("remote worker returned an invalid result state")
        output_refs = response.get("output_refs", ())
        if not isinstance(output_refs, (list, tuple)) or any(not isinstance(item, str) for item in output_refs):
            raise RuntimeError("remote worker returned invalid output references")
        return WorkerResult(task.task_id, WorkerResultState(state), tuple(output_refs), str(response.get("error", "")))

    def execute(self, task: WorkerTask) -> WorkerResult:
        raise RuntimeError("remote execution requires an explicit control-plane lease")

    def receive_artifact(self, address: str, plan: TransferPlan, data_plane: DataPlane) -> object:
        if not address.startswith("sha256:"):
            raise ValueError("remote artifact address must use sha256:<digest>")
        digest = address[7:]
        if digest != plan.reference.digest:
            raise ValueError("remote artifact address does not match transfer reference")

        def fetch_chunk(chunk):
            return self.transport.get_bytes(
                f"/v1/worker/artifacts/{digest}/chunks/{chunk.index}",
                bearer_token=self.access.access_token,
                expected_digest=chunk.digest or hashlib.sha256(b"").hexdigest(),
                offset=chunk.offset,
                size_bytes=chunk.size_bytes,
            )

        return data_plane.receive_remote(plan, fetch_chunk)


class WorkerLifecycleAuthority:
    """Control-plane authorization for worker identity and execution.

    Credentials are supplied out of band. Only hashes of enrollment and access
    credentials are retained in this authority. A registered worker is also
    bound to the exact observed hardware digest supplied at enrollment, and
    every heartbeat must present the same current observation identity until a
    deliberate re-enrollment occurs.
    """

    def __init__(self, enrollment_tokens: Mapping[str, str]):
        self._enrollment_hashes = {worker_id: self._hash(token) for worker_id, token in enrollment_tokens.items()}
        self._access_hashes: dict[str, str] = {}
        self._hardware_digests: dict[str, str] = {}
        self._heartbeats: dict[str, int] = {}
        self._used_nonces: set[str] = set()
        self._leases: dict[str, RemoteLease] = {}

    @staticmethod
    def _hash(value: str) -> str:
        if not value.strip():
            raise ValueError("credential cannot be empty")
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def register(self, worker_id: str, enrollment_token: str, now: int, hardware_observation_digest: str | None = None) -> WorkerAccess:
        expected = self._enrollment_hashes.get(worker_id)
        if expected is None or not secrets.compare_digest(expected, self._hash(enrollment_token)):
            raise PermissionError("worker enrollment is not authorized")
        if hardware_observation_digest is not None and len(hardware_observation_digest) != 64:
            raise ValueError("hardware observation digest must be a SHA-256 digest")
        token = secrets.token_urlsafe(32)
        self._access_hashes[worker_id] = self._hash(token)
        if hardware_observation_digest is not None:
            self._hardware_digests[worker_id] = hardware_observation_digest
        self._heartbeats[worker_id] = now
        return WorkerAccess(worker_id, token)

    def authorize(self, access: WorkerAccess) -> None:
        expected = self._access_hashes.get(access.worker_id)
        if expected is None or not secrets.compare_digest(expected, self._hash(access.access_token)):
            raise PermissionError("worker access is not authorized")

    def heartbeat(self, access: WorkerAccess, now: int, hardware_observation_digest: str | None = None) -> None:
        self.authorize(access)
        expected = self._hardware_digests.get(access.worker_id)
        if expected is not None and hardware_observation_digest != expected:
            raise PermissionError("worker hardware observation does not match enrolled identity")
        self._heartbeats[access.worker_id] = now

    def revoke(self, worker_id: str) -> None:
        self._access_hashes.pop(worker_id, None)
        self._hardware_digests.pop(worker_id, None)
        self._heartbeats.pop(worker_id, None)
        for lease_id, lease in tuple(self._leases.items()):
            if lease.worker_id == worker_id:
                self._leases.pop(lease_id)

    def issue_distributed_lease(
        self,
        access: WorkerAccess,
        allocation: DistributedGpuAllocation,
        task_id: str,
        now: int,
    ) -> DistributedWorkerLease:
        self.authorize(access)
        if allocation.state is not DistributedGpuAllocationState.RESERVED:
            raise PermissionError("distributed allocation is not active")
        if allocation.expires_at <= now:
            raise PermissionError("distributed allocation is expired")
        if allocation.task_id != task_id:
            raise PermissionError("distributed allocation does not belong to task")
        worker_ids = allocation.worker_ids
        try:
            node_rank = worker_ids.index(access.worker_id)
        except ValueError as exc:
            raise PermissionError("worker is not a member of distributed allocation") from exc
        local_ranks = tuple(rank for rank in allocation.ranks if rank.worker_id == access.worker_id)
        if not local_ranks:
            raise PermissionError("distributed allocation contains no GPUs for worker")
        lease = DistributedWorkerLease(
            allocation_id=allocation.allocation_id,
            task_id=allocation.task_id,
            worker_id=access.worker_id,
            world_size=allocation.world_size,
            node_count=allocation.node_count,
            node_rank=node_rank,
            ranks=local_ranks,
            gpu_uuids=tuple(rank.gpu_uuid for rank in local_ranks),
            expires_at=allocation.expires_at,
            fencing_epoch=allocation.fencing_epoch,
            execution_nonce=secrets.token_urlsafe(24),
        )
        return lease

    def authorize_distributed_execution(
        self,
        access: WorkerAccess,
        lease: DistributedWorkerLease,
        allocation: DistributedGpuAllocation,
        now: int,
    ) -> None:
        self.authorize(access)
        if allocation.state is not DistributedGpuAllocationState.RESERVED:
            raise PermissionError("distributed allocation is no longer active")
        if allocation.allocation_id != lease.allocation_id or allocation.task_id != lease.task_id:
            raise PermissionError("distributed lease allocation identity does not match")
        if allocation.fencing_epoch != lease.fencing_epoch:
            raise PermissionError("distributed lease fencing epoch does not match allocation")
        if allocation.expires_at != lease.expires_at or lease.expires_at <= now:
            raise PermissionError("distributed lease is expired")
        expected = tuple(rank for rank in allocation.ranks if rank.worker_id == access.worker_id)
        if lease.ranks != expected or lease.gpu_uuids != tuple(rank.gpu_uuid for rank in expected):
            raise PermissionError("distributed lease rank or GPU allocation does not match allocation")
        if lease.worker_id != access.worker_id:
            raise PermissionError("distributed lease belongs to another worker")
        nonce_key = f"{lease.allocation_id}:{lease.execution_nonce}"
        if nonce_key in self._used_nonces:
            raise PermissionError("distributed lease execution nonce has already been used")
        self._used_nonces.add(nonce_key)

    def issue_lease(self, access: WorkerAccess, task: WorkerTask, expires_at: int, now: int) -> RemoteLease:
        self.authorize(access)
        if expires_at <= now:
            raise ValueError("remote lease must expire in the future")
        lease = RemoteLease(secrets.token_urlsafe(24), task.task_id, access.worker_id, expires_at, task.gpu_uuids, secrets.token_urlsafe(24))
        self._leases[lease.lease_id] = lease
        return lease

    def authorize_execution(self, access: WorkerAccess, lease: RemoteLease, now: int) -> None:
        self.authorize(access)
        stored = self._leases.get(lease.lease_id)
        if stored != lease:
            raise PermissionError("remote lease is not valid")
        if lease.worker_id != access.worker_id or lease.expires_at <= now:
            raise PermissionError("remote lease is expired or owned by another worker")
        if lease.execution_nonce in self._used_nonces:
            raise PermissionError("remote lease execution nonce has already been used")
        self._used_nonces.add(lease.execution_nonce)

    def complete_lease(self, access: WorkerAccess, lease: RemoteLease, now: int) -> None:
        self.authorize(access)
        stored = self._leases.get(lease.lease_id)
        if stored != lease or lease.worker_id != access.worker_id:
            raise PermissionError("remote lease completion is not authorized")
        if lease.expires_at <= now:
            raise PermissionError("remote lease completion arrived after expiry")
        self._leases.pop(lease.lease_id, None)

    def heartbeat_age(self, worker_id: str, now: int) -> int | None:
        observed = self._heartbeats.get(worker_id)
        return None if observed is None else max(0, now - observed)

    def hardware_observation_digest(self, worker_id: str) -> str | None:
        return self._hardware_digests.get(worker_id)
