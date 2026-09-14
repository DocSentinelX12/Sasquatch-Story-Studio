from pathlib import Path

from studio.artifact_bridge import ArtifactCommitter, ArtifactLineageStore
from studio.artifacts import ContentAddressedStore
from studio.production import ProductionResponse


def test_real_output_is_committed_as_stable_content_addressed_artifact(tmp_path: Path):
    output = tmp_path / "render.mp4"
    output.write_bytes(b"real render artifact")
    source_hash = "a" * 64
    response = ProductionResponse(
        "verified-engine",
        (str(output),),
        {"canonical_source_hash": source_hash, "engine_id": "verified-engine"},
    )
    committer = ArtifactCommitter(
        ContentAddressedStore(tmp_path / "objects"),
        ArtifactLineageStore(tmp_path / "lineage.sqlite3"),
    )
    addresses = committer.commit(response, stage="animate", source_hash=source_hash)
    assert addresses[0].startswith("sha256:")
    ref = committer.resolve(addresses[0])
    assert ref.size_bytes == len(b"real render artifact")
    assert Path(ref.path).read_bytes() == b"real render artifact"


def test_artifact_commit_rejects_wrong_canonical_source(tmp_path: Path):
    output = tmp_path / "render"
    output.write_bytes(b"render")
    response = ProductionResponse("engine", (str(output),), {"canonical_source_hash": "b" * 64})
    committer = ArtifactCommitter(ContentAddressedStore(tmp_path / "objects"), ArtifactLineageStore(tmp_path / "lineage.sqlite3"))
    try:
        committer.commit(response, stage="animate", source_hash="a" * 64)
    except RuntimeError as exc:
        assert "canonical source" in str(exc)
    else:
        raise AssertionError("artifact commit accepted mismatched canonical source")
