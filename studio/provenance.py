"""Release provenance helpers."""

from dataclasses import dataclass, asdict
from hashlib import sha256
from typing import Any
import json


@dataclass(frozen=True)
class ArtifactProvenance:
    artifact_id: str
    stage: str
    source_hash: str
    adapter_id: str | None = None
    adapter_version: str | None = None
    parameters: dict[str, Any] | None = None
    seed: int | None = None


def hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def canonical_json_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hash_text(payload)


def as_record(item: ArtifactProvenance) -> dict[str, Any]:
    return asdict(item)
