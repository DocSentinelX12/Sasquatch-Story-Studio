"""Creator-asset indexing and deterministic resolution."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from hashlib import sha256
from pathlib import Path
import json
from typing import Any

@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    path: str
    kind: str
    content_sha256: str
    creator_owned: bool
    source_asset_id: str | None = None
    metadata: dict[str, Any] | None = None

def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def index_assets(root: str | Path, *, creator_owned: bool = True) -> list[AssetRecord]:
    base = Path(root)
    if not base.exists():
        raise FileNotFoundError(base)
    records: list[AssetRecord] = []
    for path in sorted(p for p in base.rglob("*") if p.is_file() and not p.name.startswith(".")):
        relative = path.relative_to(base).as_posix()
        asset_id = sha256(relative.encode("utf-8")).hexdigest()[:24]
        kind = path.suffix.lower().lstrip(".") or "unknown"
        records.append(AssetRecord(asset_id, relative, kind, sha256_file(path), creator_owned, metadata={"size_bytes": path.stat().st_size}))
    return records

def resolve_asset(records: list[AssetRecord], asset_id: str) -> AssetRecord:
    matches = [record for record in records if record.asset_id == asset_id]
    if not matches:
        raise RuntimeError(f"Required creator asset is missing: {asset_id}")
    if len(matches) != 1:
        raise RuntimeError(f"Asset identity is ambiguous: {asset_id}")
    return matches[0]

def require_creator_asset(record: AssetRecord) -> None:
    if not record.creator_owned:
        raise RuntimeError(f"Non-creator asset cannot replace a required creator asset: {record.asset_id}")

def write_index(records: list[AssetRecord], destination: str | Path) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps([asdict(record) for record in records], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target
