from pathlib import Path

import pytest

from studio.runtime_verification import build_runtime_evidence, probe_version, sha256_file


def test_sha256_file_hashes_real_checkpoint(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.bin"
    checkpoint.write_bytes(b"real checkpoint bytes")
    assert len(sha256_file(checkpoint)) == 64


def test_empty_checkpoint_is_rejected(tmp_path: Path) -> None:
    checkpoint = tmp_path / "empty.bin"
    checkpoint.write_bytes(b"")
    with pytest.raises(RuntimeError, match="missing or empty"):
        sha256_file(checkpoint)


def test_version_probe_executes_configured_runtime() -> None:
    output = probe_version(("python", "-c", "print('runtime-2.0')"))
    assert output == "runtime-2.0"


def test_version_probe_does_not_invent_missing_executable() -> None:
    with pytest.raises(RuntimeError, match="unavailable"):
        probe_version(("definitely-not-a-real-runtime-command", "--version"))


def test_evidence_requires_real_checkpoint_and_execution(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.bin"
    checkpoint.write_bytes(b"checkpoint")
    evidence = build_runtime_evidence(
        engine_id="test-engine",
        engine_version="2.0.0",
        executable="python",
        version_observation="runtime-2.0",
        checkpoint_path=str(checkpoint),
        license_source="https://example.invalid/license",
        license_evidence="operator-verified-license-record",
        execution_verified=True,
    )
    assert evidence.checkpoint_sha256 == sha256_file(checkpoint)
    assert evidence.execution_verified is True


def test_evidence_rejects_unverified_execution(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.bin"
    checkpoint.write_bytes(b"checkpoint")
    with pytest.raises(ValueError, match="execution_verified"):
        build_runtime_evidence(
            engine_id="test-engine",
            engine_version="2.0.0",
            executable="python",
            version_observation="runtime-2.0",
            checkpoint_path=str(checkpoint),
            license_source="https://example.invalid/license",
            license_evidence="operator-verified-license-record",
            execution_verified=False,
        )
