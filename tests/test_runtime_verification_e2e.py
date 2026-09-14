import sys
from pathlib import Path

from studio.engine_registry import EngineSpec, SQLiteEngineVerificationStore
from studio.runtime_verification import verify_engine_runtime


def test_runtime_verification_requires_and_records_real_execution(tmp_path: Path):
    checkpoint = tmp_path / "model.bin"
    checkpoint.write_bytes(b"real checkpoint bytes")
    version_script = "print('engine verification harness version')"
    render_script = "from pathlib import Path; Path(__import__('sys').argv[1]).write_bytes(b'real runtime output')"
    engine = EngineSpec(
        "verification-harness", "harness", "local verification harness", "test-only",
        ("animation",), (sys.executable,), "verification",
    )
    output = tmp_path / "verification.out"
    evidence = verify_engine_runtime(
        engine=engine,
        version_command=(sys.executable, "-c", version_script),
        execution_command=(sys.executable, "-c", render_script, "{output}"),
        checkpoint_path=checkpoint,
        output_path=output,
        license_source="test harness record",
        license_evidence="test fixture only, never a production engine record",
        recorded_at=100,
    )
    assert output.read_bytes() == b"real runtime output"
    assert len(evidence.checkpoint_sha256) == 64
    assert len(evidence.runtime_output_sha256) == 64
    assert evidence.version_observation == "engine verification harness version"

    store = SQLiteEngineVerificationStore(tmp_path / "engines.db")
    store.save(evidence.to_record())
    saved = store.snapshot()
    assert len(saved) == 1
    assert saved[0].runtime_output_sha256 == evidence.runtime_output_sha256


def test_runtime_verification_does_not_accept_execution_without_explicit_output(tmp_path: Path):
    checkpoint = tmp_path / "model.bin"
    checkpoint.write_bytes(b"checkpoint")
    engine = EngineSpec("verification-harness", "harness", "local verification harness", "test-only", ("animation",), (sys.executable,), "verification")
    try:
        verify_engine_runtime(
            engine=engine,
            version_command=(sys.executable, "-c", "print('harness')"),
            execution_command=(sys.executable, "-c", "print('no artifact')"),
            checkpoint_path=checkpoint,
            output_path=tmp_path / "out",
            license_source="test harness record",
            license_evidence="test fixture only, never a production engine record",
            recorded_at=1,
        )
    except ValueError as exc:
        assert "{output}" in str(exc)
    else:
        raise AssertionError("verification accepted an execution command without explicit output")
