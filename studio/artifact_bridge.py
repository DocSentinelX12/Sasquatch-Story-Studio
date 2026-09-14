"""Commit real adapter outputs into creator-owned content-addressed storage."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .artifacts import ArtifactRef, ContentAddressedStore
from .production import ProductionResponse


@dataclass(frozen=True)
class ArtifactLineage:
    digest: str
    size_bytes: int
    stage: str
    adapter_id: str
    source_hash: str
    provenance: dict[str, object]


class ArtifactLineageStore:
    """Durable metadata index for immutable artifact objects."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS artifact_lineage ("
                "digest TEXT PRIMARY KEY, size_bytes INTEGER NOT NULL, stage TEXT NOT NULL, "
                "adapter_id TEXT NOT NULL, source_hash TEXT NOT NULL, provenance_json TEXT NOT NULL)"
            )

    def record(self, lineage: ArtifactLineage) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO artifact_lineage VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(digest) DO UPDATE SET "
                "size_bytes=excluded.size_bytes, stage=excluded.stage, adapter_id=excluded.adapter_id, "
                "source_hash=excluded.source_hash, provenance_json=excluded.provenance_json",
                (lineage.digest, lineage.size_bytes, lineage.stage, lineage.adapter_id, lineage.source_hash, json.dumps(lineage.provenance, sort_keys=True)),
            )

    def get(self, digest: str) -> ArtifactLineage | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT digest, size_bytes, stage, adapter_id, source_hash, provenance_json FROM artifact_lineage WHERE digest=?",
                (digest,),
            ).fetchone()
        if row is None:
            return None
        return ArtifactLineage(row[0], row[1], row[2], row[3], row[4], json.loads(row[5]))


class ArtifactCommitter:
    """Turn verified adapter file outputs into stable artifact identities."""

    def __init__(self, store: ContentAddressedStore, lineage: ArtifactLineageStore):
        self.store = store
        self.lineage = lineage

    def commit(self, response: ProductionResponse, *, stage: str, source_hash: str) -> tuple[str, ...]:
        if not response.output_refs:
            raise RuntimeError("cannot commit an adapter response with no outputs")
        if response.provenance.get("canonical_source_hash") != source_hash:
            raise RuntimeError("adapter provenance does not match canonical source hash")
        committed: list[str] = []
        for raw in response.output_refs:
            path = Path(raw).expanduser().resolve()
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f"adapter output is not a real non-empty file: {raw}")
            ref: ArtifactRef = self.store.put_file(path)
            lineage = ArtifactLineage(ref.digest, ref.size_bytes, stage, response.adapter_id, source_hash, dict(response.provenance))
            self.lineage.record(lineage)
            committed.append(f"sha256:{ref.digest}")
        return tuple(committed)

    def resolve(self, address: str) -> ArtifactRef:
        prefix = "sha256:"
        if not address.startswith(prefix):
            raise ValueError("artifact address must use sha256:<digest>")
        digest = address[len(prefix):]
        if not self.store.exists(digest):
            raise FileNotFoundError(digest)
        lineage = self.lineage.get(digest)
        if lineage is None:
            raise RuntimeError(f"artifact object has no durable lineage record: {digest}")
        return ArtifactRef(digest, lineage.size_bytes, str(self.store._path(digest)))
