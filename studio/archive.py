"""Deterministic archive manifests and artifact lineage."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
import json


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    path: str
    sha256: str
    media_type: str
    stage: str


def hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_artifacts(root: str | Path, stage: str) -> tuple[ArtifactRecord, ...]:
    base = Path(root)
    if not base.exists():
        raise FileNotFoundError(base)
    records = []
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        relative = path.relative_to(base).as_posix()
        artifact_id = sha256(relative.encode("utf-8")).hexdigest()[:24]
        records.append(ArtifactRecord(artifact_id, relative, hash_file(path), path.suffix.lower().lstrip("."), stage))
    return tuple(records)


def write_archive_manifest(records: tuple[ArtifactRecord, ...], destination: str | Path) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"artifacts": [asdict(record) for record in records]}
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target
