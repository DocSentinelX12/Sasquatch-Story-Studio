"""Evidence-backed runtime verification for production engines.

Verification is an observation procedure, not a flag. It records the exact
runtime version, hashes the real checkpoint/model, executes the configured
runtime command, and hashes the real output. Nothing in this module downloads
or invents an engine, model, endpoint, or credential.
"""
from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .engine_registry import EngineSpec, EngineVerificationRecord


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
    runtime_output_sha256: str
    recorded_at: int
    source_revision: str | None = None

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
            "runtime_output_sha256": self.runtime_output_sha256,
        }
        for name, value in required.items():
            if not value or not value.strip():
                raise ValueError(f"{name} is required")
        if self.source_revision is not None and not self.source_revision.strip():
            raise ValueError("source_revision cannot be empty when supplied")
        for name in ("checkpoint_sha256", "runtime_output_sha256"):
            value = getattr(self, name)
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower()):
                raise ValueError(f"{name} must be a SHA-256 hex digest")
        if self.recorded_at < 0:
            raise ValueError("recorded_at cannot be negative")

    def to_record(self) -> EngineVerificationRecord:
        return EngineVerificationRecord(
            engine_id=self.engine_id,
            engine_version=self.engine_version,
            executable=self.executable,
            version_observation=self.version_observation,
            checkpoint_path=self.checkpoint_path,
            checkpoint_sha256=self.checkpoint_sha256,
            license_source=self.license_source,
            license_evidence=self.license_evidence,
            runtime_output_sha256=self.runtime_output_sha256,
            recorded_at=self.recorded_at,
            source_revision=self.source_revision,
        )


def sha256_path(path: str | Path) -> str:
    """Hash one model file or a model directory deterministically.

    Directory hashes include each relative file path and its bytes in sorted
    relative-path order. Empty directories are not included because they do not
    contribute model content.
    """
    target = Path(path).expanduser().resolve()
    if target.is_file():
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if target.stat().st_size == 0:
            raise RuntimeError(f"checkpoint/model file is missing or empty: {target}")
        return digest.hexdigest()

    if not target.is_dir():
        raise RuntimeError(f"checkpoint/model path does not exist: {target}")

    files = sorted(item for item in target.rglob("*") if item.is_file())
    if not files:
        raise RuntimeError(f"checkpoint/model directory contains no files: {target}")

    digest = hashlib.sha256()
    for item in files:
        relative = item.relative_to(target).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: str | Path) -> str:
    """Hash a single non-empty file, preserving the original file-only API."""
    target = Path(path).expanduser().resolve()
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"checkpoint/model file is missing or empty: {target}")
    return sha256_path(target)


def _run(command: Sequence[str], *, cwd: Path | None, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    if not command or any(not item for item in command):
        raise ValueError("command is required")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    try:
        completed = subprocess.run(
            tuple(command), cwd=cwd, check=False, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"configured runtime executable is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"configured runtime command timed out: {command[0]}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"configured runtime command failed with exit code {completed.returncode}: {detail}")
    return completed


def probe_version(command: Sequence[str], *, timeout_seconds: int = 30) -> str:
    """Run the configured version command and return its observed output."""
    completed = _run(command, cwd=None, timeout_seconds=timeout_seconds)
    output = (completed.stdout or completed.stderr).strip()
    if not output:
        raise RuntimeError("runtime version probe produced no output")
    return output


def verify_engine_runtime(
    *,
    engine: EngineSpec,
    version_command: Sequence[str],
    execution_command: Sequence[str],
    checkpoint_path: str | Path,
    output_path: str | Path,
    license_source: str,
    license_evidence: str,
    recorded_at: int,
    working_directory: str | Path | None = None,
    timeout_seconds: int = 3600,
    source_revision: str | None = None,
) -> RuntimeEvidence:
    """Perform a real configured verification run and return immutable evidence.

    ``execution_command`` must explicitly contain the literal ``{output}``
    placeholder. The verifier substitutes only that declared output path. The
    command is otherwise untouched.
    """
    if not engine.id.strip():
        raise ValueError("engine identity is required")
    if not engine.runtime_command:
        raise ValueError(f"engine {engine.id} has no runtime command")
    if "{output}" not in tuple(execution_command):
        raise ValueError("execution_command must contain the explicit {output} placeholder")
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    workdir = Path(working_directory).expanduser().resolve() if working_directory else None
    if workdir is not None and not workdir.is_dir():
        raise RuntimeError(f"runtime working directory does not exist: {workdir}")

    version_observation = probe_version(version_command, timeout_seconds=min(timeout_seconds, 60))
    checkpoint = Path(checkpoint_path).expanduser().resolve()
    checkpoint_digest = sha256_path(checkpoint)
    command = tuple(str(item) for item in execution_command)
    command = tuple(str(output) if item == "{output}" else item for item in command)
    _run(command, cwd=workdir, timeout_seconds=timeout_seconds)
    output_digest = sha256_path(output)

    return RuntimeEvidence(
        engine_id=engine.id,
        engine_version=engine.version_family,
        executable=command[0],
        version_observation=version_observation,
        checkpoint_path=str(checkpoint),
        checkpoint_sha256=checkpoint_digest,
        license_source=license_source,
        license_evidence=license_evidence,
        runtime_output_sha256=output_digest,
        recorded_at=recorded_at,
        source_revision=source_revision,
    )
