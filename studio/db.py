"""Database engine and session management (SQLite, WAL mode)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

# Foreign keys must be enabled per-connection on SQLite.
_engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(_engine, "connect")
def _sqlite_pragma(dbapi_connection, _record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_all() -> None:
    from . import models  # noqa: F401  (register mappings)
    from .models.base import Base

    settings.database_absolute.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(_engine)
    ensure_schema_upgrades()


# ---------------------------------------------------------------------------
# Lightweight additive migrations (SQLite ALTER TABLE ... ADD COLUMN).
# Only ADDs columns that are missing; never drops or rewrites existing data.
# ---------------------------------------------------------------------------

EXPECTED_EXTRA_COLUMNS: dict[str, dict[str, str]] = {
    "characters": {
        "description": "TEXT",
        "standard_appearance": "TEXT",
        "current_outfit": "TEXT",
        "standard_props": "JSON",
        "personality_rules": "JSON",
        "visual_rules": "JSON",
        "never_changes": "JSON",
        "life_status": "VARCHAR(32) DEFAULT 'draft'",
    },
    "character_references": {
        "label": "TEXT",
        "description": "TEXT",
        "tags": "JSON",
        "notes": "TEXT",
        "approval_status": "VARCHAR(32) DEFAULT 'registered'",
    },
    "asset_versions": {
        "status": "VARCHAR(32) DEFAULT 'registered'",
    },
}


def ensure_schema_upgrades() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(_engine)
    with _engine.begin() as connection:
        for table, columns in EXPECTED_EXTRA_COLUMNS.items():
            if table not in inspector.get_table_names():
                continue
            existing = {col["name"] for col in inspector.get_columns(table)}
            for column, ddl in columns.items():
                if column not in existing:
                    connection.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                    )
