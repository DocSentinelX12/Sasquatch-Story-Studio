from pathlib import Path
import sys
import hashlib

import pytest

from studio.engine_registry import EngineSpec, get_catalog_engine
from studio.runtime_verification import probe_version, sha256_file, sha256_path, verify_engine_runtime


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
    output = probe_version((sys.executable, "-c", "print('runtime-2.0')"))
    assert output == "runtime-2.0"


def test_version_probe_does_not_invent_missing_executable() -> None:
    with pytest.raises(RuntimeError, match="unavailable"):
        probe_version(("definitely-not-a-real-runtime-command", "--version"))


def test_verification_requires_real_checkpoint_and_execution(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.bin"
    checkpoint.write_bytes(b"checkpoint")
    output = tmp_path / "verified-output.bin"
    engine = EngineSpec("verification-harness", "harness", "local verification harness", "test-only", ("animation",), (sys.executable,), "verification")
    evidence = verify_engine_runtime(
        engine=engine,
        version_command=(sys.executable, "-c", "print('runtime-2.0')"),
        execution_command=(sys.executable, "-c", "from pathlib import Path; Path(__import__('sys').argv[1]).write_bytes(b'verified')", "{output}"),
        checkpoint_path=checkpoint,
        output_path=output,
        license_source="test harness record",
        license_evidence="test fixture only, never a production engine record",
        recorded_at=1,
    )
    assert evidence.checkpoint_sha256 == sha256_file(checkpoint)
    assert evidence.runtime_output_sha256 == sha256_file(output)


def test_verification_rejects_missing_output_placeholder(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.bin"
    checkpoint.write_bytes(b"checkpoint")
    engine = EngineSpec("verification-harness", "harness", "local verification harness", "test-only", ("animation",), (sys.executable,), "verification")
    with pytest.raises(ValueError, match="\{output\}"):
        verify_engine_runtime(
            engine=engine,
            version_command=(sys.executable, "-c", "print('runtime')"),
            execution_command=(sys.executable, "-c", "print('no output')"),
            checkpoint_path=checkpoint,
            output_path=tmp_path / "out",
            license_source="test harness record",
            license_evidence="test fixture only, never a production engine record",
            recorded_at=1,
        )


def test_sha256_path_hashes_model_directory_deterministically(tmp_path: Path) -> None:
    model = tmp_path / "hunyuan"
    (model / "text_encoder").mkdir(parents=True)
    (model / "transformer").mkdir()
    (model / "transformer" / "weights.bin").write_bytes(b"weights")
    (model / "text_encoder" / "config.json").write_text("{}", encoding="utf-8")

    first = sha256_path(model)
    (model / "text_encoder" / "config.json").touch()
    assert sha256_path(model) == first

    (model / "text_encoder" / "config.json").write_text("{\"changed\":true}", encoding="utf-8")
    assert sha256_path(model) != first


def test_sha256_path_rejects_empty_model_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="contains no files"):
        sha256_path(empty)


def test_hunyuan_catalog_entry_is_video_only_and_not_runtime_verified_by_catalogue_presence():
    engine = get_catalog_engine("hunyuanvideo-1.5")
    assert engine.capabilities == ("video_generation",)
    assert engine.runtime_verified is False
    assert engine.license_verified is False
    assert engine.checkpoint_verified is False
    assert engine.commercial_use_review_required is True
    assert "European Union" in (engine.territory_restriction or "")
    assert engine.official_source == "https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5"
