"""Verified transfer of distributed worker outputs into creator-owned CAS."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .artifact_bridge import ArtifactCommitter
from .data_plane import TransferChunk, TransferPlan, TransferResult, DataPlane


class DistributedArtifactCommitter:
    """Materialize an authenticated worker artifact, verify it, then commit it."""

    def __init__(self, data_plane: DataPlane, artifact_committer: ArtifactCommitter):
        self.data_plane = data_plane
        self.artifact_committer = artifact_committer

    def commit(
        self,
        plan: TransferPlan,
        fetch_chunk: Callable[[TransferChunk], bytes],
        *,
        stage: str,
        adapter_id: str,
        source_hash: str,
        provenance: dict[str, object],
    ) -> str:
        if not plan.reference.digest:
            raise ValueError("distributed artifact reference is required")
        if plan.reference.size_bytes <= 0:
            raise ValueError("distributed production artifact must be non-empty")
        if not stage.strip() or not adapter_id.strip() or not source_hash.strip():
            raise ValueError("distributed artifact commit metadata is required")
        result: TransferResult = self.data_plane.receive_remote(plan, fetch_chunk)
        if not result.verified:
            raise RuntimeError("distributed artifact transfer did not reach verified state")
        destination = Path(plan.destination).expanduser().resolve()
        if not destination.is_file():
            raise RuntimeError("verified distributed artifact is missing from its destination")
        address = self.artifact_committer.commit_file(
            destination,
            stage=stage,
            adapter_id=adapter_id,
            source_hash=source_hash,
            provenance={
                **provenance,
                "distributed_transfer_id": plan.transfer_id,
                "distributed_artifact_digest": plan.reference.digest,
                "distributed_artifact_size_bytes": plan.reference.size_bytes,
                "distributed_completed_chunks": list(result.completed_chunks),
            },
        )
        expected = "sha256:" + plan.reference.digest
        if address != expected:
            raise RuntimeError("committed distributed artifact digest does not match the verified transfer reference")
        return address
