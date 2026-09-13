"""Canonical asset and model registry records."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AssetRecord:
    id: str
    kind: Literal["character", "location", "prop", "voice", "rig", "music", "sfx", "other"]
    source_path: str
    source_hash: str
    status: Literal["source", "derived", "approved", "retired"] = "source"
    license_record_id: str | None = None


@dataclass(frozen=True)
class ModelRecord:
    id: str
    version: str
    provider: str
    capabilities: tuple[str, ...]
    license: str
    license_source: str
    verification_status: Literal["verified", "pending", "rejected"]
    runtime_requirements: dict[str, str]

    def usable(self) -> bool:
        return self.verification_status == "verified"
