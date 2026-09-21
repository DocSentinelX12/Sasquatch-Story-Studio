from pathlib import Path

from studio.artifact_bridge import ArtifactCommitter, ArtifactLineageStore
from studio.artifacts import ContentAddressedStore
from studio.data_plane import DataPlane
from studio.distributed_artifacts import DistributedArtifactCommitter


def test_distributed_artifact_is_transferred_verified_and_committed(tmp_path: Path):
    source = tmp_path / "worker-output.bin"
    source.write_bytes(b"0123456789" * 1000)
    plane = DataPlane(tmp_path / "transfer-state", chunk_size=97)
    reference = plane.reference_for(source)
    plan = plane.plan(reference, source, "ignored-local-source", transfer_id="distributed-commit-1")

    destination = tmp_path / "materialized.bin"
    plan = type(plan)(plan.transfer_id, plan.reference, "worker://worker-a/artifact", str(destination), plan.chunks)
    committer = ArtifactCommitter(
        ContentAddressedStore(tmp_path / "objects"),
        ArtifactLineageStore(tmp_path / "lineage.sqlite3"),
    )
    service = DistributedArtifactCommitter(plane, committer)

    def fetch(chunk):
        with source.open("rb") as handle:
            handle.seek(chunk.offset)
            return handle.read(chunk.size_bytes)

    address = service.commit(
        plan,
        fetch,
        stage="animate",
        adapter_id="wan2.2",
        source_hash="a" * 64,
        provenance={
            "canonical_source_hash": "a" * 64,
            "allocation_id": "allocation-1",
            "task_id": "task-1",
            "worker_id": "worker-a",
        },
    )

    assert address == "sha256:" + reference.digest
    resolved = committer.resolve(address)
    assert Path(resolved.path).read_bytes() == source.read_bytes()
    lineage = committer.lineage.get(reference.digest)
    assert lineage is not None
    assert lineage.provenance["allocation_id"] == "allocation-1"


def test_distributed_artifact_commit_rejects_wrong_expected_address(tmp_path: Path):
    source = tmp_path / "worker-output.bin"
    source.write_bytes(b"payload")
    plane = DataPlane(tmp_path / "transfer-state", chunk_size=4)
    reference = plane.reference_for(source)
    plan = plane.plan(reference, source, tmp_path / "materialized.bin", transfer_id="distributed-commit-2")
    committer = ArtifactCommitter(
        ContentAddressedStore(tmp_path / "objects"),
        ArtifactLineageStore(tmp_path / "lineage.sqlite3"),
    )
    service = DistributedArtifactCommitter(plane, committer)

    def fetch(chunk):
        return b"tampered"[:chunk.size_bytes]

    try:
        service.commit(
            plan,
            fetch,
            stage="animate",
            adapter_id="wan2.2",
            source_hash="b" * 64,
            provenance={"canonical_source_hash": "b" * 64},
        )
    except IOError as exc:
        assert "checksum" in str(exc) or "content verification" in str(exc)
    else:
        raise AssertionError("tampered distributed artifact was accepted")


def test_distributed_artifact_commit_rejects_provenance_source_mismatch(tmp_path: Path):
    source = tmp_path / "worker-output.bin"
    source.write_bytes(b"payload")
    plane = DataPlane(tmp_path / "transfer-state", chunk_size=4)
    reference = plane.reference_for(source)
    plan = plane.plan(reference, source, tmp_path / "materialized.bin", transfer_id="distributed-commit-3")
    committer = ArtifactCommitter(
        ContentAddressedStore(tmp_path / "objects"),
        ArtifactLineageStore(tmp_path / "lineage.sqlite3"),
    )
    service = DistributedArtifactCommitter(plane, committer)

    def fetch(chunk):
        return source.read_bytes()[chunk.offset:chunk.offset + chunk.size_bytes]

    try:
        service.commit(
            plan,
            fetch,
            stage="animate",
            adapter_id="wan2.2",
            source_hash="a" * 64,
            provenance={"canonical_source_hash": "b" * 64},
        )
    except RuntimeError as exc:
        assert "canonical source" in str(exc)
    else:
        raise AssertionError("distributed artifact provenance mismatch was accepted")
