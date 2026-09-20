"""Real multi-node distributed GPU execution over authenticated worker control.

The coordinator launches one real process group per allocation. Each worker runs
the same verified application command under torchrun with the exact allocation's
node rank and local GPU set. Rendezvous coordinates are supplied by deployment,
never invented by the studio.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .distributed_gpu import DistributedGpuAllocation
from .remote_worker import DistributedWorkerLease, WorkerAccess


@dataclass(frozen=True)
class DistributedLaunchSpec:
    """Exact executable and rendezvous configuration for one distributed job."""

    executable: str
    command: tuple[str, ...]
    rendezvous_id: str
    rendezvous_host: str
    rendezvous_port: int
    timeout_seconds: int = 3600
    max_restarts: int = 0
    output_path: str | None = None

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("distributed launcher executable is required")
        if not self.command or any(not item for item in self.command):
            raise ValueError("distributed application command is required")
        if not self.rendezvous_id.strip():
            raise ValueError("distributed rendezvous id is required")
        if not self.rendezvous_host.strip():
            raise ValueError("distributed rendezvous host is required")
        if not 1 <= self.rendezvous_port <= 65535:
            raise ValueError("distributed rendezvous port must be between 1 and 65535")
        if self.timeout_seconds < 1:
            raise ValueError("distributed execution timeout must be positive")
        if self.max_restarts < 0:
            raise ValueError("distributed max_restarts cannot be negative")
        if self.output_path is not None and not self.output_path.strip():
            raise ValueError("distributed output_path cannot be empty")

    @property
    def command_sha256(self) -> str:
        payload = "\0".join(self.command).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def argv(self, lease: DistributedWorkerLease) -> tuple[str, ...]:
        local_world_size = len(lease.ranks)
        if local_world_size < 1:
            raise ValueError("distributed lease contains no local ranks")
        if lease.world_size < local_world_size:
            raise ValueError("distributed lease world size is smaller than local world size")
        return (
            self.executable,
            "--nnodes",
            str(lease.node_count),
            "--nproc-per-node",
            str(local_world_size),
            "--node-rank",
            str(lease.node_rank),
            "--rdzv-id",
            self.rendezvous_id,
            "--rdzv-backend",
            "c10d",
            "--rdzv-endpoint",
            f"{self.rendezvous_host}:{self.rendezvous_port}",
            "--max-restarts",
            str(self.max_restarts),
            *(str(self.output_path) if item == "{output}" and self.output_path is not None else item for item in self.command),
        )


@dataclass(frozen=True)
class DistributedExecutionEvidence:
    allocation_id: str
    task_id: str
    worker_id: str
    node_rank: int
    global_ranks: tuple[int, ...]
    gpu_uuids: tuple[str, ...]
    command_sha256: str
    stdout_sha256: str
    stderr_sha256: str
    exit_code: int
    started_at: int
    finished_at: int
    output_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.allocation_id.strip() or not self.task_id.strip() or not self.worker_id.strip():
            raise ValueError("distributed execution evidence identity is required")
        if self.node_rank < 0 or any(rank < 0 for rank in self.global_ranks):
            raise ValueError("distributed execution ranks must be non-negative")
        for digest in (self.command_sha256, self.stdout_sha256, self.stderr_sha256):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("execution evidence digests must be lowercase SHA-256 values")
        if self.finished_at < self.started_at:
            raise ValueError("execution evidence timestamps are invalid")


class DistributedWorkerTransport(Protocol):
    def post_json(self, path: str, payload: Mapping[str, Any], *, bearer_token: str) -> dict[str, Any]:
        ...


def _lease_payload(lease: DistributedWorkerLease) -> dict[str, Any]:
    return {
        "allocation_id": lease.allocation_id,
        "task_id": lease.task_id,
        "worker_id": lease.worker_id,
        "world_size": lease.world_size,
        "node_count": lease.node_count,
        "node_rank": lease.node_rank,
        "ranks": [rank.__dict__ for rank in lease.ranks],
        "gpu_uuids": list(lease.gpu_uuids),
        "expires_at": lease.expires_at,
        "fencing_epoch": lease.fencing_epoch,
        "execution_nonce": lease.execution_nonce,
    }


def _parse_lease(raw: Mapping[str, Any]) -> DistributedWorkerLease:
    from .distributed_gpu import RankAssignment

    return DistributedWorkerLease(
        allocation_id=str(raw["allocation_id"]),
        task_id=str(raw["task_id"]),
        worker_id=str(raw["worker_id"]),
        world_size=int(raw["world_size"]),
        node_count=int(raw["node_count"]),
        node_rank=int(raw["node_rank"]),
        ranks=tuple(RankAssignment(**item) for item in raw["ranks"]),
        gpu_uuids=tuple(str(item) for item in raw["gpu_uuids"]),
        expires_at=int(raw["expires_at"]),
        fencing_epoch=int(raw["fencing_epoch"]),
        execution_nonce=str(raw["execution_nonce"]),
    )


class DistributedProcessExecutor:
    """Execute the exact distributed command on one authenticated worker."""

    def __init__(self, spec: DistributedLaunchSpec):
        self.spec = spec

    def execute(
        self,
        payload: Mapping[str, Any],
        lease: DistributedWorkerLease,
        access: WorkerAccess,
        now: int,
    ) -> Mapping[str, Any]:
        task_id = str(payload.get("task_id", ""))
        allocation_id = str(payload.get("allocation_id", ""))
        if task_id != lease.task_id or allocation_id != lease.allocation_id:
            raise PermissionError("distributed execution payload does not match lease identity")

        argv = self.spec.argv(lease)
        environment = os.environ.copy()
        environment["CUDA_VISIBLE_DEVICES"] = ",".join(lease.gpu_uuids)
        environment["MASTER_ADDR"] = self.spec.rendezvous_host
        environment["MASTER_PORT"] = str(self.spec.rendezvous_port)
        environment["WORLD_SIZE"] = str(lease.world_size)
        environment["NODE_RANK"] = str(lease.node_rank)
        environment["GROUP_RANK"] = str(lease.node_rank)
        environment["LOCAL_WORLD_SIZE"] = str(len(lease.ranks))
        environment["TORCHELASTIC_RUN_ID"] = self.spec.rendezvous_id

        started = int(time.time())
        try:
            completed = subprocess.run(
                argv,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                timeout=self.spec.timeout_seconds,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"distributed launcher is unavailable: {self.spec.executable}") from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("distributed worker execution exceeded its configured timeout") from exc
        finished = int(time.time())

        stdout = completed.stdout or b""
        stderr = completed.stderr or b""
        output_refs: tuple[str, ...] = ()
        if completed.returncode == 0 and self.spec.output_path is not None and lease.node_rank == 0:
            output_path = os.path.abspath(self.spec.output_path)
            if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
                raise RuntimeError("distributed rank-zero execution completed without the configured output artifact")
            with open(output_path, "rb") as output_handle:
                output_refs = ("sha256:" + hashlib.sha256(output_handle.read()).hexdigest(),)

        evidence = DistributedExecutionEvidence(
            allocation_id=lease.allocation_id,
            task_id=lease.task_id,
            worker_id=access.worker_id,
            node_rank=lease.node_rank,
            global_ranks=tuple(rank.global_rank for rank in lease.ranks),
            gpu_uuids=lease.gpu_uuids,
            command_sha256=self.spec.command_sha256,
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            stderr_sha256=hashlib.sha256(stderr).hexdigest(),
            exit_code=completed.returncode,
            started_at=started,
            finished_at=finished,
        )
        if completed.returncode != 0:
            detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
            return {
                "state": "failed",
                "error": f"distributed process exited with code {completed.returncode}: {detail}",
                "execution_evidence": evidence.__dict__,
            }
        return {
            "state": "completed",
            "output_refs": list(output_refs),
            "execution_evidence": evidence.__dict__,
        }


class DistributedWorkerExecutor:
    """Coordinator-side remote executor for one exact distributed allocation."""

    def __init__(self, transport: DistributedWorkerTransport, access: WorkerAccess):
        self.transport = transport
        self.access = access

    def execute(self, allocation: DistributedGpuAllocation, lease: DistributedWorkerLease, spec: DistributedLaunchSpec) -> dict[str, Any]:
        if lease.allocation_id != allocation.allocation_id or lease.task_id != allocation.task_id:
            raise ValueError("distributed lease does not match allocation")
        expected = tuple(rank for rank in allocation.ranks if rank.worker_id == lease.worker_id)
        if lease.ranks != expected:
            raise ValueError("distributed lease ranks do not match allocation")
        if lease.world_size != allocation.world_size or lease.node_count != allocation.node_count:
            raise ValueError("distributed lease dimensions do not match allocation")
        response = self.transport.post_json(
            "/v1/worker/execute-distributed",
            {
                "allocation_id": allocation.allocation_id,
                "task_id": allocation.task_id,
                "lease": _lease_payload(lease),
                "launch": {
                    "executable": spec.executable,
                    "command": list(spec.command),
                    "rendezvous_id": spec.rendezvous_id,
                    "rendezvous_host": spec.rendezvous_host,
                    "rendezvous_port": spec.rendezvous_port,
                    "timeout_seconds": spec.timeout_seconds,
                    "max_restarts": spec.max_restarts,
                    "output_path": spec.output_path,
                },
            },
            bearer_token=self.access.access_token,
        )
        state = response.get("state")
        if state not in {"completed", "failed"}:
            raise RuntimeError("distributed worker returned an invalid execution state")
        return response

class DistributedExecutionCoordinator:
    """Launch every allocation member concurrently and close the allocation atomically."""

    def __init__(self, allocator, lease_issuers: Mapping[str, Any], executors: Mapping[str, DistributedWorkerExecutor]):
        self.allocator = allocator
        self.lease_issuers = dict(lease_issuers)
        self.executors = dict(executors)

    def execute(self, allocation: DistributedGpuAllocation, spec: DistributedLaunchSpec, now: int) -> tuple[dict[str, Any], ...]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if allocation.expires_at <= now:
            raise RuntimeError("distributed allocation is expired")
        if tuple(sorted(self.executors)) != allocation.worker_ids:
            raise ValueError("distributed executors must cover every allocation worker exactly")
        if tuple(sorted(self.lease_issuers)) != allocation.worker_ids:
            raise ValueError("distributed lease issuers must cover every allocation worker exactly")

        leases = {}
        for worker_id in allocation.worker_ids:
            leases[worker_id] = self.lease_issuers[worker_id](allocation, now)

        results = {}
        with ThreadPoolExecutor(max_workers=allocation.node_count) as pool:
            futures = {
                pool.submit(self.executors[worker_id].execute, allocation, leases[worker_id], spec): worker_id
                for worker_id in allocation.worker_ids
            }
            for future in as_completed(futures):
                worker_id = futures[future]
                try:
                    results[worker_id] = future.result()
                except Exception as exc:
                    results[worker_id] = {"state": "failed", "error": str(exc)}

        ordered = tuple(results[worker_id] for worker_id in allocation.worker_ids)
        finished_now = int(time.time())
        if all(result.get('state') == 'completed' for result in ordered):
            if finished_now >= allocation.expires_at:
                self.allocator.expire(finished_now)
            else:
                self.allocator.complete(allocation.allocation_id, allocation.fencing_epoch, finished_now)
        else:
            if finished_now >= allocation.expires_at:
                self.allocator.expire(finished_now)
            else:
                self.allocator.fail(allocation.allocation_id, allocation.fencing_epoch, finished_now)
        return ordered
