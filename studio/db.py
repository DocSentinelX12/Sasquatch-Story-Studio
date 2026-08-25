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
    # --- Phase 3 (story layer) ---
    "story_bibles": {
        "status": "VARCHAR(32) DEFAULT 'draft'",
    },
    "episodes": {
        "summary": "TEXT",
        "story_id": "INTEGER",
        "script_status": "VARCHAR(32) DEFAULT 'draft'",
    },
    "acts": {
        "summary": "TEXT",
        "beginning": "TEXT",
        "middle": "TEXT",
        "ending": "TEXT",
    },
    "scenes": {
        "weather": "TEXT",
        "summary": "TEXT",
        "emotional_tone": "TEXT",
        "visual_direction": "TEXT",
        "continuity_notes": "TEXT",
        "dependency_notes": "TEXT",
    },
    "locations": {
        "environment": "TEXT",
        "time_of_day_notes": "TEXT",
        "weather_notes": "TEXT",
        "visual_rules": "JSON",
        "continuity_notes": "TEXT",
        "approval_status": "VARCHAR(32) DEFAULT 'registered'",
    },
    "props": {
        "owner_character_id": "INTEGER",
        "continuity_notes": "TEXT",
        "approval_status": "VARCHAR(32) DEFAULT 'registered'",
    },
    # --- Phase 4 (storyboard/shot layer) ---
    "generation_jobs": {
        "provider_job_id": "TEXT",
        "package_version": "INTEGER",
        "attempt": "INTEGER",
        "error_code": "VARCHAR(64)",
        "translated_request": "JSON",
        "submitted_references": "JSON",
        "usage": "JSON",
        "poll_metadata": "JSON",
    },
    "generation_results": {
        "shot_id": "INTEGER",
        "provider_key": "VARCHAR(64)",
        "duration_seconds": "REAL",
        "resolution": "VARCHAR(32)",
        "status": "VARCHAR(32) DEFAULT 'needs_review'",
        "file_size": "INTEGER",
    },
    "shots": {
        "title": "TEXT",
        "description": "TEXT",
        "camera_notes": "TEXT",
        "lens_framing": "TEXT",
        "composition": "TEXT",
        "subject_position": "TEXT",
        "character_action": "TEXT",
        "facial_expression": "TEXT",
        "environment_action": "TEXT",
        "transition": "TEXT",
        "lighting": "TEXT",
        "weather": "TEXT",
        "continuity_notes": "TEXT",
        "character_state_notes": "TEXT",
        "prop_state_notes": "TEXT",
        "location_state_notes": "TEXT",
        "prev_shot_id": "INTEGER",
        "next_shot_id": "INTEGER",
        "generation_status": "VARCHAR(32) DEFAULT 'pending'",
    },
}

# Legacy Phase 1 status values → Phase 3 vocabulary (data-preserving rewrite
# of a single TEXT column; runs once).
LEGACY_STATUS_MAP = {
    "episodes": {
        "planned": "draft",
        "outline": "development",
        "storyboard": "in_production",
        "shot_building": "in_production",
        "generating": "in_production",
        "editing": "in_production",
        "qc": "in_production",
        "exported": "complete",
        "released": "complete",
    },
    "scenes": {
        "planned": "draft",
        "written": "needs_review",
        "boarded": "ready_for_storyboard",
        "shot_ready": "ready_for_storyboard",
        "generating": "in_production",
    },
    "generation_jobs": {
        "provider_job_id": "TEXT",
        "package_version": "INTEGER",
        "attempt": "INTEGER",
        "error_code": "VARCHAR(64)",
        "translated_request": "JSON",
        "submitted_references": "JSON",
        "usage": "JSON",
        "poll_metadata": "JSON",
    },
    "generation_results": {
        "shot_id": "INTEGER",
        "provider_key": "VARCHAR(64)",
        "duration_seconds": "REAL",
        "resolution": "VARCHAR(32)",
        "status": "VARCHAR(32) DEFAULT 'needs_review'",
        "file_size": "INTEGER",
    },
    "shots": {
        "planned": "draft",
        "ready": "needs_review",
        "queued": "generating",
    },
    "story_bibles": {
        # seeded creator canon starts approved
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
        # normalize legacy statuses once
        for table, mapping in LEGACY_STATUS_MAP.items():
            if table not in inspector.get_table_names():
                continue
            for old, new in mapping.items():
                connection.execute(
                    text(f"UPDATE {table} SET status = :new WHERE status = :old"),
                    {"old": old, "new": new},
                )
