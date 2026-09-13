"""Explicit human approval record for final release."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
from pathlib import Path


@dataclass(frozen=True)
class ApprovalRecord:
    episode_id: str
    story_id: str
    approved: bool
    reviewer: str
    reviewed_manifest_hash: str
    reviewed_at: str
    notes: str = ""


def create_approval(*, episode_id: str, story_id: str, reviewer: str, manifest_hash: str, approved: bool, notes: str = "") -> ApprovalRecord:
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    if not manifest_hash.strip():
        raise ValueError("manifest hash is required")
    return ApprovalRecord(episode_id, story_id, approved, reviewer, manifest_hash, datetime.now(timezone.utc).isoformat(), notes)


def write_approval(record: ApprovalRecord, destination: str | Path) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(record), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
