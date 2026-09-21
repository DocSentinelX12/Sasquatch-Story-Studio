"""Evidence-producing boundary for measured distributed GPU communication.

This module never infers communication capability from provider, region,
worker count, or topology locality. A worker execution boundary must first
return an actual command result. The verifier converts that measured result
into the canonical evidence objects consumed by the fabric registry and
distributed allocator.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .distributed_gpu import DistributedNCCLEvidence, GpuDirectNetworkEvidence


@dataclass(frozen=True)
class CommunicationCommandResult:
    executable: str
    executable_sha256: str
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("communication executable is required")
        if not self.command:
            raise ValueError("communication command is required")
        if len(self.executable_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.executable_sha256.lower()
        ):
            raise ValueError("executable_sha256 must be a SHA-256 hex digest")

    @property
    def output_sha256(self) -> str:
        payload = self.stdout.encode("utf-8") + b"\\x00" + self.stderr.encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class FabricCommunicationVerifier:
    """Turn real worker command results into canonical communication evidence."""

    @staticmethod
    def _require_success(result: CommunicationCommandResult) -> None:
        if result.exit_code != 0:
            raise RuntimeError("communication command did not complete successfully")
        if not result.stdout and not result.stderr:
            raise RuntimeError("successful communication command produced no output")

    @staticmethod
    def distributed_nccl_evidence(
        result: CommunicationCommandResult,
        *,
        worker_gpu_mapping: tuple[tuple[str, tuple[str, ...]], ...],
        topology_digests: tuple[tuple[str, str], ...],
        rendezvous_id: str,
    ) -> DistributedNCCLEvidence:
        FabricCommunicationVerifier._require_success(result)
        worker_ids = tuple(worker_id for worker_id, _ in worker_gpu_mapping)
        if tuple(sorted(worker_ids)) != worker_ids or len(worker_ids) < 2:
            raise ValueError("distributed NCCL worker IDs must be sorted and contain at least two workers")
        if any(not gpus for _, gpus in worker_gpu_mapping):
            raise ValueError("distributed NCCL verification requires GPUs on every worker")
        if tuple(sorted(dict(topology_digests))) != worker_ids:
            raise ValueError("distributed NCCL topology digests must exactly match worker IDs")
        if not rendezvous_id.strip():
            raise ValueError("distributed NCCL rendezvous identity is required")
        return DistributedNCCLEvidence(
            worker_ids=worker_ids,
            gpu_uuids_by_worker=worker_gpu_mapping,
            world_size=sum(len(gpus) for _, gpus in worker_gpu_mapping),
            command=result.command,
            exit_code=result.exit_code,
            output_sha256=result.output_sha256,
            rendezvous_id=rendezvous_id,
            topology_digests=topology_digests,
        )

    @staticmethod
    def gpu_direct_evidence(
        result: CommunicationCommandResult,
        *,
        worker_pairs: tuple[tuple[str, str], ...],
        gpu_pairs: tuple[tuple[str, str, str, str], ...],
        transport: str,
    ) -> GpuDirectNetworkEvidence:
        FabricCommunicationVerifier._require_success(result)
        if not transport.strip():
            raise ValueError("GPU-direct transport is required")
        return GpuDirectNetworkEvidence(
            worker_pairs=worker_pairs,
            gpu_pairs=gpu_pairs,
            transport=transport,
            command=result.command,
            exit_code=result.exit_code,
            output_sha256=result.output_sha256,
        )
