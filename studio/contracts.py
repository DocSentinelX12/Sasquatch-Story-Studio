"""Small, dependency-free validation helpers for canonical production contracts."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def require_keys(value: dict[str, Any], keys: tuple[str, ...], context: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise ValueError(f"{context} missing required fields: {missing}")


def require_nonempty_string(value: Any, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{field} must be a non-empty string")
    return value


def require_unique_ids(items: list[dict[str, Any]], field: str, context: str) -> None:
    ids = [item.get(field) for item in items]
    if any(not isinstance(item_id, str) or not item_id.strip() for item_id in ids):
        raise ValueError(f"{context} contains an item without a valid {field}")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{context} contains duplicate {field} values")
