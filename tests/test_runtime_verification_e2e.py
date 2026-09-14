import sys
from pathlib import Path

from studio.engine_registry import EngineSpec, RuntimeEngineRegistry, SQLiteEngineVerificationStore
from studio.runtime_verification import verify_engine_runtime


def test_runtime_verification_requires_and_records_real_execution(tmp_path: Path):
    checkpoint = tmp_path / "model.bin"
    checkpoint.write_bytes(b"real checkpoint bytes")
    version_script = "import sys; print('engine 7.4.1')"
    render_script = "from pathlib import Path; Path(__import__('sys').argv[1]).write_bytes(b'real runtime output')"
    engine = EngineSpec(
        "test-engine", "7.x", "https://example.invalid/engine", "MIT",
        ("animation",), (sys.executable,), "test", 
    )
    output = tmp_path / "verification.out"
    evidence = verify_engine_runtime(
        engine=engine,
        version_command=(sys.executable, "-c", version_script),
        execution_command=(sys.executable, "-c", render_script, "{output}"),
        checkpoint_path=checkpoint,
        output_path=output,
        license_source="operator evidence",
        license_evidence="verified test license record",
        recorded_at=100,
    )
    assert output.read_bytes() == b"real runtime output"
    assert len(evidence.checkpoint_sha256) == 64
    assert len(evidence.runtime_output_sha256) == 64
    assert evidence.version_observation == "engine 7.4.1"

    store = SQLiteEngineVerificationStore(tmp_path / "engines.db")
    store.save(evidence.to_record())
    promoted = RuntimeEngineRegistry(store).get("test-engine")
    assert promoted.runtime_verified
    assert promoted.license_verified
    assert promoted.checkpoint_verified
    assert promoted.verification_evidence


def test_runtime_verification_does_not_accept_execution_without_explicit_output(tmp_path: Path):
    checkpoint = tmp_path / "model.bin"
    checkpoint.write_bytes(b"checkpoint")
    engine = EngineSpec("test-engine", "1", "source", "MIT", ("animation",), (sys.executable,), "test")
    try:
        verify_engine_runtime(
            engine=engine,
            version_command=(sys.executable, "-c", "print('1')"),
            execution_command=(sys.executable, "-c", "print('no artifact')"),
            checkpoint_path=checkpoint,
            output_path=tmp_path / "out",
            license_source="source",
            license_evidence="evidence",
            recorded_at=1,
        )
    except ValueError as exc:
        assert "{output}" in str(exc)
    else:
        raise AssertionError("verification accepted an execution command without explicit output")
