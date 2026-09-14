"""Content-addressed local artifact storage for durable production outputs."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class ArtifactRef:
    digest: str
    size_bytes: int
    path: str

    def __post_init__(self) -> None:
        if len(self.digest) != 64 or any(char not in "0123456789abcdef" for char in self.digest):
            raise ValueError("artifact digest must be a lowercase SHA-256 hex digest")
        if self.size_bytes < 0:
            raise ValueError("artifact size cannot be negative")
        if not self.path:
            raise ValueError("artifact path is required")


class ContentAddressedStore:
    """Store immutable bytes by SHA-256 without replacing an existing artifact."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("invalid artifact digest")
        return self.objects / digest[:2] / digest[2:]

    @staticmethod
    def _temporary_path(destination: Path) -> Path:
        return destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")

    def put_bytes(self, data: bytes) -> ArtifactRef:
        digest = hashlib.sha256(data).hexdigest()
        destination = self._path(digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.stat().st_size != len(data) or not self.verify(ArtifactRef(digest, len(data), str(destination))):
                raise IOError("content-addressed object exists but failed integrity verification")
            return ArtifactRef(digest, len(data), str(destination))
        temporary = self._temporary_path(destination)
        try:
            temporary.write_bytes(data)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                raise IOError("artifact verification failed before commit")
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if destination.stat().st_size != len(data) or not self.verify(ArtifactRef(digest, len(data), str(destination))):
                    raise IOError("concurrent artifact write failed integrity verification")
            finally:
                temporary.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)
        ref = ArtifactRef(digest, len(data), str(destination))
        if not self.verify(ref):
            raise IOError("artifact verification failed after commit")
        return ref

    def put_file(self, source: str | Path, chunk_size: int = 1024 * 1024) -> ArtifactRef:
        source_path = Path(source)
        digest = hashlib.sha256()
        size = 0
        with source_path.open("rb") as stream:
            while chunk := stream.read(chunk_size):
                digest.update(chunk)
                size += len(chunk)
        artifact_digest = digest.hexdigest()
        destination = self._path(artifact_digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        ref = ArtifactRef(artifact_digest, size, str(destination))
        if destination.exists():
            if not self.verify(ref):
                raise IOError("content-addressed object exists but failed integrity verification")
            return ref
        temporary = self._temporary_path(destination)
        try:
            with source_path.open("rb") as source_stream, temporary.open("wb") as target:
                while chunk := source_stream.read(chunk_size):
                    target.write(chunk)
            if not self.verify(ArtifactRef(artifact_digest, size, str(temporary))):
                raise IOError("artifact verification failed before commit")
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if not self.verify(ref):
                    raise IOError("concurrent artifact write failed integrity verification")
            finally:
                temporary.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)
        if not self.verify(ref):
            raise IOError("artifact verification failed after commit")
        return ref

    def open(self, digest: str) -> BinaryIO:
        path = self._path(digest)
        if not path.is_file():
            raise FileNotFoundError(digest)
        return path.open("rb")

    def exists(self, digest: str) -> bool:
        return self._path(digest).is_file()

    def verify(self, ref: ArtifactRef) -> bool:
        path = Path(ref.path)
        if not path.is_file() or path.stat().st_size != ref.size_bytes:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest() == ref.digest


@dataclass(frozen=True)
class ReplicaRecord:
    digest: str
    replica_id: str
    verified: bool = False


class ReplicaManifest:
    """Durable JSON metadata for replica placement, separate from object bytes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> tuple[ReplicaRecord, ...]:
        if not self.path.exists():
            return ()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return tuple(ReplicaRecord(item["digest"], item["replica_id"], item["verified"]) for item in data)

    def record(self, replica: ReplicaRecord) -> None:
        records = {(item.digest, item.replica_id): item for item in self.load()}
        previous = records.get((replica.digest, replica.replica_id))
        if previous is not None and previous.verified and not replica.verified:
            replica = previous
        records[(replica.digest, replica.replica_id)] = replica
        payload = [
            {"digest": item.digest, "replica_id": item.replica_id, "verified": item.verified}
            for item in sorted(records.values(), key=lambda item: (item.digest, item.replica_id))
        ]
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
