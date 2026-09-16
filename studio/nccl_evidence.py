"""Explicit evidence for NCCL collective communication readiness."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NCCLTestEvidence:
    executable: str
    executable_sha256: str
    command: tuple[str, ...]
    exit_code: int
    output_sha256: str
    gpu_uuids: tuple[str, ...]
    topology_digest: str


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise ValueError(f"{field} must be a SHA-256 hex digest")


def validate_nccl_evidence(evidence: NCCLTestEvidence) -> None:
    if not evidence.executable.strip():
        raise ValueError("NCCL test executable is required")
    if not evidence.command:
        raise ValueError("NCCL test command is required")
    if not evidence.gpu_uuids:
        raise ValueError("NCCL evidence must identify the participating GPUs")
    _require_sha256(evidence.executable_sha256, "executable_sha256")
    _require_sha256(evidence.output_sha256, "output_sha256")
    _require_sha256(evidence.topology_digest, "topology_digest")
    if evidence.exit_code != 0:
        raise RuntimeError("NCCL test did not complete successfully")
