"""Shared API helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import DeclarativeBase, Session

from ..db import get_session  # re-exported as the FastAPI dependency


def get_db():
    session: Session = next(get_session())
    try:
        yield session
    finally:
        session.close()


def row_to_dict(obj: DeclarativeBase, **extra: Any) -> dict:
    """Serialize an ORM row's column attributes to a JSON-safe dict."""
    data: dict[str, Any] = {}
    mapper = inspect(type(obj))
    for attr in mapper.column_attrs:
        value = getattr(obj, attr.key)
        if isinstance(value, datetime):
            value = value.isoformat()
        data[attr.key] = value
    # rename `metadata_json` columns surfaced as 'metadata_json' already fine
    data.update(extra)
    return data


def slugify(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "untitled"
