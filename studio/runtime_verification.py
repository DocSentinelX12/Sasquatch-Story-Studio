"""Evidence-backed runtime verification for production engines.

Catalog metadata never promotes an engine. Promotion requires an actual configured
runtime, an exact version observation, a real checkpoint/model file with a hash,
and explicit license evidence supplied by the operator or verifier.
"""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class RuntimeEvidence:
    engine_id: str
    engine_version: str
    executable: str
    version_observation: str
    checkpoint_path: str
    checkpoint_sha256: str
    license_source: str
    license_evidence: str
    execution_verified: bool

    def __post_init__(self) -> None:
        required = {
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "executable": self.executable,
            "version_observation": self.version_observation,
            "checkpoint_path": self.checkpoint_path,
            "checkpoint_sha256": self.checkpoint_sha256,
            "license_source": self.license_source,
            "license_evidence": self.license_evidence,
        }
        for name, value in required.items():
            if not value or not value.strip():
                raise ValueError(f"{name} is required")
        if len(self.checkpoint_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.checkpoint_sha256.lower()):
            raise ValueError("checkpoint_sha256 must be a SHA-256 hex digest")
        if not self.execution_verified:
            raise ValueError("execution_verified must be true for production evidence")


def sha256_file(path: str | Path) -> str:
    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file() or file_path.stat().st_size == 0:
        raise RuntimeError(f"checkpoint/model file is missing or empty: {file_path}")
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_version(command: Sequence[str], *, timeout_seconds: int = 30) -> str:
    """Run the configured version command. No executable or fallback is invented."""
    if not command or any(not item for item in command):
        raise ValueError("version command is required")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    try:
        completed = subprocess.run(
            tuple(command),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"configured runtime executable is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("configured runtime version probe timed out") from exc
    output = (completed.stdout or completed.stderr).strip()
    if completed.returncode != 0 or not output:
        raise RuntimeError(f"runtime version probe failed with exit code {completed.returncode}: {output}")
    return output


def build_runtime_evidence(
    *,
    engine_id: str,
    engine_version: str,
    executable: str,
    version_observation: str,
    checkpoint_path: str,
    license_source: str,
    license_evidence: str,
    execution_verified: bool,
) -> RuntimeEvidence:
    """Create immutable evidence only after hashing the real checkpoint/model file."""
    return RuntimeEvidence(
        engine_id=engine_id,
        engine_version=engine_version,
        executable=executable,
        version_observation=version_observation,
        checkpoint_path=str(Path(checkpoint_path).expanduser().resolve()),
        checkpoint_sha256=sha256_file(checkpoint_path),
        license_source=license_source,
        license_evidence=license_evidence,
        execution_verified=execution_verified,
    )
