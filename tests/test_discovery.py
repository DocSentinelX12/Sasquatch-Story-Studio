from pathlib import Path

from studio.discovery import discover_compute_resource
from studio.engine_registry import get_engine


def test_discovery_does_not_claim_wan_without_real_entrypoint(tmp_path: Path):
    engine = get_engine("wan2.2")
    resource = discover_compute_resource("worker-test", engine_roots={"wan2.2": tmp_path}, engines=(engine,))
    assert "wan2.2" not in resource.installed_engines
    assert resource.cpu_cores >= 1
    assert resource.memory_bytes >= 1


def test_discovery_detects_only_a_real_entrypoint(tmp_path: Path):
    (tmp_path / "generate.py").write_text("# test fixture\n", encoding="utf-8")
    engine = get_engine("wan2.2")
    resource = discover_compute_resource("worker-test", engine_roots={"wan2.2": tmp_path}, engines=(engine,))
    assert resource.installed_engines == ("wan2.2",)
    assert resource.capabilities == ("image_generation", "video_generation")
