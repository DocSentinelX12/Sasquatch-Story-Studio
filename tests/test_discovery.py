from pathlib import Path

from studio.discovery import discover_compute_resource
from studio.engine_registry import EngineSpec


def test_discovery_does_not_claim_python_engines_without_real_entrypoint(tmp_path: Path):
    engine = EngineSpec(
        "test-python-engine",
        "test",
        "https://github.com/Wan-Video/Wan2.2",
        "Apache-2.0",
        ("video_generation",),
        ("python", "generate.py"),
        "high",
    )
    resource = discover_compute_resource("worker-test", engine_roots={"test-python-engine": tmp_path}, engines=(engine,))
    assert "test-python-engine" not in resource.installed_engines
    assert resource.cpu_cores >= 1
    assert resource.memory_bytes >= 1


def test_discovery_detects_only_a_real_entrypoint(tmp_path: Path):
    (tmp_path / "generate.py").write_text("# test fixture\n", encoding="utf-8")
    engine = EngineSpec(
        "test-python-engine",
        "test",
        "https://github.com/Wan-Video/Wan2.2",
        "Apache-2.0",
        ("video_generation",),
        ("python", "generate.py"),
        "high",
    )
    resource = discover_compute_resource("worker-test", engine_roots={"test-python-engine": tmp_path}, engines=(engine,))
    assert resource.installed_engines == ("test-python-engine",)
    assert resource.capabilities == ("video_generation",)
