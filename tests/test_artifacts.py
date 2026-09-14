from pathlib import Path

from studio.artifacts import ArtifactRef, ContentAddressedStore, ReplicaManifest, ReplicaRecord


def test_content_addressed_store_deduplicates_and_verifies(tmp_path: Path):
    store = ContentAddressedStore(tmp_path / "objects")
    first = store.put_bytes(b"episode-master")
    second = store.put_bytes(b"episode-master")
    assert first == second
    assert store.exists(first.digest)
    assert store.verify(first)
    with store.open(first.digest) as stream:
        assert stream.read() == b"episode-master"


def test_content_addressed_store_put_file_uses_content_hash(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"real-media-bytes")
    store = ContentAddressedStore(tmp_path / "objects")
    ref = store.put_file(source)
    assert ref.size_bytes == len(b"real-media-bytes")
    assert store.verify(ref)


def test_replica_manifest_is_durable_and_verified_state_is_not_downgraded(tmp_path: Path):
    manifest = ReplicaManifest(tmp_path / "replicas.json")
    ref = ArtifactRef("a" * 64, 10, "/local/object")
    manifest.record(ReplicaRecord(ref.digest, "worker-a", verified=True))
    manifest.record(ReplicaRecord(ref.digest, "worker-a", verified=False))
    manifest.record(ReplicaRecord(ref.digest, "worker-b", verified=True))

    restored = ReplicaManifest(tmp_path / "replicas.json").load()
    assert restored == (
        ReplicaRecord(ref.digest, "worker-a", verified=True),
        ReplicaRecord(ref.digest, "worker-b", verified=True),
    )
