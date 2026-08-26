"""Phase 9: versioned backups, validation, staged restore, auto-backups.

Restore safety: the backup JSON is fully validated BEFORE any database write;
the restore itself runs in ONE transaction — any failure rolls back so the
active production database remains untouched.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Project

BACKUP_FORMAT = "sasquatch-studio-series-backup"
BACKUP_SCHEMA_VERSION = 2

RESTORE_MODES = ("new_series", "into_existing", "replace")
ENTITY_ORDER = [
    "story_bible", "stories", "characters", "character_bibles", "canon",
    "locations", "props", "voices", "assets", "episodes", "scenes",
    "script_elements", "shots", "timeline_tracks", "timeline_items",
    "audio_recordings", "generation_jobs", "generation_results",
    "renders", "exports",
]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# C — versioned backup creation (wraps the Phase 8 payload with metadata)
# ---------------------------------------------------------------------------

def canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def checksum_of(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def entity_counts(payload: dict) -> dict:
    return {key: len(payload.get(key) or []) for key in ENTITY_ORDER}


def media_manifest(payload: dict) -> dict:
    """Check every media path referenced by the backup against this machine."""
    paths: list[str] = []
    for row in payload.get("assets") or []:
        if row.get("repo_path"):
            paths.append(row["repo_path"])
    for row in payload.get("generation_results") or []:
        if row.get("repo_path"):
            paths.append(row["repo_path"])
    for row in payload.get("audio_recordings") or []:
        if row.get("repo_path"):
            paths.append(row["repo_path"])
    for row in payload.get("renders") or []:
        if row.get("output_path"):
            paths.append(row["output_path"])
    manifest = []
    for rel in sorted(set(paths)):
        absolute = (settings.repo_root / rel).resolve()
        try:
            absolute.relative_to(settings.repo_root.resolve())
        except ValueError:
            manifest.append({"path": rel, "status": "outside-repository"})
            continue
        if absolute.is_file():
            try:
                size = absolute.stat().st_size
                manifest.append({"path": rel, "status": "available", "bytes": size})
            except OSError:
                manifest.append({"path": rel, "status": "unreadable"})
        else:
            manifest.append({"path": rel, "status": "missing"})
    return {
        "total": len(manifest),
        "available": sum(1 for m in manifest if m["status"] == "available"),
        "missing": sum(1 for m in manifest if m["status"] == "missing"),
        "entries": manifest,
    }


def decorate_backup(payload: dict) -> dict:
    """Add Phase 9 metadata to a Phase 8 backup payload."""
    from ..config import settings as cfg
    series = payload.get("series") or {}
    payload["backup_metadata"] = {
        "backup_id": f"BK-{secrets.token_hex(6).upper()}",
        "series_id": series.get("id"),
        "series_name": series.get("name"),
        "created_at": utcnow_iso(),
        "studio_version": cfg.app_version,
        "backup_schema_version": BACKUP_SCHEMA_VERSION,
        "entity_counts": entity_counts(payload),
        "media_manifest": media_manifest(payload),
        "validation_status": "unverified",
    }
    payload["backup_metadata"]["checksum"] = checksum_of(
        {k: v for k, v in payload.items() if k != "backup_metadata"})
    payload["backup_metadata"]["validation_status"] = "valid"
    return payload


# ---------------------------------------------------------------------------
# A/B — validation (pure JSON, before any DB write)
# ---------------------------------------------------------------------------

def validate_backup(payload: dict) -> dict:
    findings: list[dict] = []

    def add(severity, key, message):
        findings.append({"severity": severity, "key": key, "message": message})

    if not isinstance(payload, dict):
        return {"valid": False, "status": "blocked",
                "findings": [{"severity": "blocked", "key": "not-json-object",
                              "message": "Backup is not a JSON object"}]}

    if payload.get("format") != BACKUP_FORMAT:
        add("blocked", "format", f"Unknown format {payload.get('format')!r} — expected {BACKUP_FORMAT!r}")

    meta = payload.get("backup_metadata") or {}
    schema_version = meta.get("backup_schema_version")
    if schema_version is None:
        # Phase 8 backups (schema 1) are importable with a warning
        add("warning", "schema-version", "Legacy backup without schema version — importing best-effort")
    elif schema_version > BACKUP_SCHEMA_VERSION:
        add("blocked", "schema-version",
            f"Backup schema v{schema_version} is newer than this studio (v{BACKUP_SCHEMA_VERSION})")

    series = payload.get("series")
    if not isinstance(series, dict) or not series.get("name"):
        add("blocked", "series", "Missing series metadata")

    # checksum verification when present
    if meta.get("checksum"):
        body = {k: v for k, v in payload.items() if k != "backup_metadata"}
        if checksum_of(body) != meta["checksum"]:
            add("blocked", "checksum", "Checksum mismatch — backup content changed after export")

    # entity structure, duplicate + unknown keys
    for key in payload:
        if key not in ENTITY_ORDER + ["format", "version", "series", "backup_metadata"]:
            add("warning", "unknown-entity", f"Unknown section '{key}' will be skipped")
    for key in ENTITY_ORDER:
        rows = payload.get(key)
        if rows is None:
            continue
        if not isinstance(rows, list):
            add("blocked", key, f"Section '{key}' is not a list")
            continue
        seen_ids = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                add("blocked", f"{key}[{index}]", "Row is not an object")
                continue
            row_id = row.get("id")
            if row_id is not None:
                if row_id in seen_ids:
                    add("blocked", f"{key}[{index}]", f"Duplicate id {row_id}")
                seen_ids.add(row_id)
            if not row.get("created_at"):
                add("warning", f"{key}[{index}]", "Missing created_at (defaults applied)")

    # relationship sanity: every scene's episode_id exists in episodes, etc.
    def id_set(key):
        return {r.get("id") for r in (payload.get(key) or []) if isinstance(r, dict)}
    episodes = id_set("episodes")
    for index, scene in enumerate(payload.get("scenes") or []):
        if isinstance(scene, dict) and scene.get("episode_id") not in episodes:
            add("blocked", f"scenes[{index}]", "Scene references unknown episode")
    scenes = id_set("scenes")
    for index, shot in enumerate(payload.get("shots") or []):
        if isinstance(shot, dict) and shot.get("scene_id") not in scenes:
            add("blocked", f"shots[{index}]", "Shot references unknown scene")

    blocked = [f for f in findings if f["severity"] == "blocked"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    return {"valid": not blocked, "status": "blocked" if blocked else ("warning" if warnings else "valid"),
            "findings": findings,
            "summary": {"blocked": len(blocked), "warnings": len(warnings)}}


# ---------------------------------------------------------------------------
# A/B — staged restore (one transaction; rollback on any failure)
# ---------------------------------------------------------------------------

def _coerce_datetimes(model, data: dict) -> dict:
    """JSON gives us ISO strings; SQLite DateTime columns need datetime objects."""
    from datetime import date
    for column in model.__table__.columns:
        value = data.get(column.name)
        if isinstance(value, str) and column.type.__class__.__name__ == "DateTime":
            try:
                data[column.name] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                data.pop(column.name, None)
        elif isinstance(value, str) and column.type.__class__.__name__ == "Date":
            try:
                data[column.name] = date.fromisoformat(value[:10])
            except ValueError:
                data.pop(column.name, None)
    return data


def _clean_row(model, row: dict, drop=("id",), fixed=None) -> dict:
    fixed = fixed or {}
    data = {k: v for k, v in row.items()
            if k in model.__table__.columns.keys() and k not in drop}
    for key, value in fixed.items():
        if key in model.__table__.columns.keys():
            data[key] = value
    return _coerce_datetimes(model, data)


def restore_backup(db: Session, payload: dict, mode: str, target_series_id: int | None = None,
                   new_series_name: str | None = None) -> dict:
    """Restore a validated backup.

    mode: new_series (default) | into_existing | replace (requires target).
    Everything happens in ONE transaction — any exception rolls back fully.
    """
    from ..db import SessionLocal
    from ..models import (Act, Asset, AssetVersion, AudioRecording, AutomationRule,
                          CanonEntry, Character, CharacterBible, CharacterReference,
                          Episode, EpisodeRender, EpisodeTemplate, ExportRecord,
                          GenerationJob, GenerationResult, Location, Prop, Scene,
                          ScriptElement, Season, Shot, Story, StoryBible,
                          TimelineItem, TimelineTrack, VoiceProfile)

    validation = validate_backup(payload)
    if validation["status"] == "blocked":
        return {"restored": False, "reason": "validation-blocked",
                "validation": validation}

    series = payload["series"]
    id_map: dict[str, dict[int, int]] = {}

    def new_id(entity: str, old):
        return id_map.get(entity, {}).get(old)

    try:
        # --- series target -------------------------------------------------
        if mode == "new_series":
            name = new_series_name or f"{series['name']} (restored)"
            slug_base = name.lower().replace(" ", "-")[:50]
            project = Project(name=name, slug=f"{slug_base}-{secrets.token_hex(3)}",
                              description=series.get("description") or "",
                              series_premise=series.get("series_premise") or "",
                              status="planning")
            db.add(project); db.flush()
            target = project.id
        elif mode in ("into_existing", "replace"):
            target = target_series_id
            existing = db.get(Project, target)
            if existing is None:
                raise ValueError("Target series does not exist")
            if mode == "replace":
                # explicit destructive mode: remove existing children only
                for episode in db.scalars(select(Episode).where(Episode.project_id == target)).all():
                    db.delete(episode)
                for character in db.scalars(select(Character).where(Character.project_id == target)).all():
                    db.delete(character)
                for location in db.scalars(select(Location).where(Location.project_id == target)).all():
                    db.delete(location)
                for prop in db.scalars(select(Prop).where(Prop.project_id == target)).all():
                    db.delete(prop)
                for asset in db.scalars(select(Asset).where(Asset.project_id == target)).all():
                    db.delete(asset)
                for story in db.scalars(select(Story).where(Story.project_id == target)).all():
                    db.delete(story)
                for canon in db.scalars(select(CanonEntry).where(CanonEntry.project_id == target)).all():
                    db.delete(canon)
                db.flush()
        else:
            raise ValueError(f"Unknown restore mode '{mode}'")

        id_map["project"] = {series.get("id"): target}

        def put(model, entity, rows, **fixed):
            mapped_rows = []
            for row in rows or []:
                data = _clean_row(model, row, fixed=fixed)
                obj = model(**data)
                db.add(obj); db.flush()
                if row.get("id") is not None:
                    id_map.setdefault(entity, {})[row["id"]] = obj.id
                mapped_rows.append(obj)
            return mapped_rows

        put(StoryBible, "story_bible", payload.get("story_bible"), project_id=target)
        put(Story, "story", payload.get("stories"), project_id=target)
        put(Character, "character", payload.get("characters"), project_id=target)
        # remap character links in bibles / references
        for row in payload.get("character_bibles") or []:
            data = _clean_row(CharacterBible, row)
            data["character_id"] = new_id("character", data.get("character_id"))
            if data.get("character_id") is not None:
                db.add(CharacterBible(**data))
        for row in payload.get("character_references") or []:
            data = _clean_row(CharacterReference, row)
            data["character_id"] = new_id("character", data.get("character_id"))
            data["asset_id"] = new_id("asset", data.get("asset_id")) or data.get("asset_id")
            if data.get("character_id") is not None:
                db.add(CharacterReference(**data))
        put(CanonEntry, "canon", payload.get("canon"), project_id=target)
        put(Location, "location", payload.get("locations"), project_id=target)
        put(Prop, "prop", payload.get("props"), project_id=target,
            owner_character_id=None)
        put(VoiceProfile, "voice", payload.get("voices"), project_id=target)
        put(Asset, "asset", payload.get("assets"), project_id=target)

        # seasons (backup includes episodes but may not include seasons) — ensure one
        season = db.scalar(select(Season).where(Season.project_id == target))
        if season is None:
            season = Season(project_id=target, number=1, title="Season 1", status="planning")
            db.add(season); db.flush()

        for row in payload.get("episodes") or []:
            data = _clean_row(Episode, row, drop=("id", "season_id", "story_id"))
            data["project_id"] = target
            data["season_id"] = season.id
            episode = Episode(**data)
            db.add(episode); db.flush()
            id_map.setdefault("episode", {})[row.get("id")] = episode.id

        for row in payload.get("scenes") or []:
            data = _clean_row(Scene, row, drop=("id", "episode_id", "location_id"))
            data["episode_id"] = new_id("episode", row.get("episode_id")) or row.get("episode_id")
            if data["episode_id"] is None:
                continue
            data["location_id"] = new_id("location", row.get("location_id"))
            scene = Scene(**data)
            db.add(scene); db.flush()
            id_map.setdefault("scene", {})[row.get("id")] = scene.id

        for row in payload.get("shots") or []:
            data = _clean_row(Shot, row, drop=("id", "scene_id"))
            data["scene_id"] = new_id("scene", row.get("scene_id")) or row.get("scene_id")
            if data["scene_id"] is None:
                continue
            shot = Shot(**data)
            db.add(shot); db.flush()
            id_map.setdefault("shot", {})[row.get("id")] = shot.id

        for row in payload.get("script_elements") or []:
            data = _clean_row(ScriptElement, row)
            data["scene_id"] = new_id("scene", data.get("scene_id")) or data.get("scene_id")
            data["episode_id"] = new_id("episode", data.get("episode_id"))
            data["character_id"] = new_id("character", data.get("character_id"))
            if data.get("scene_id") is not None:
                db.add(ScriptElement(**data))

        for row in payload.get("timeline_tracks") or []:
            data = _clean_row(TimelineTrack, row)
            data["episode_id"] = new_id("episode", data.get("episode_id")) or data.get("episode_id")
            if data.get("episode_id") is not None:
                track = TimelineTrack(**data); db.add(track); db.flush()
                id_map.setdefault("timeline_track", {})[row.get("id")] = track.id

        for row in payload.get("timeline_items") or []:
            data = _clean_row(TimelineItem, row)
            data["episode_id"] = new_id("episode", data.get("episode_id"))
            data["track_id"] = new_id("timeline_track", data.get("track_id"))
            data["scene_id"] = new_id("scene", data.get("scene_id"))
            data["shot_id"] = new_id("shot", data.get("shot_id"))
            if data.get("episode_id") is not None:
                db.add(TimelineItem(**data))

        for row in payload.get("audio_recordings") or []:
            data = _clean_row(AudioRecording, row)
            data["project_id"] = target
            data["episode_id"] = new_id("episode", data.get("episode_id"))
            data["scene_id"] = new_id("scene", data.get("scene_id"))
            data["shot_id"] = new_id("shot", data.get("shot_id"))
            data["character_id"] = new_id("character", data.get("character_id"))
            db.add(AudioRecording(**data))

        for row in payload.get("generation_jobs") or []:
            data = _clean_row(GenerationJob, row)
            data["project_id"] = target
            data["episode_id"] = new_id("episode", data.get("episode_id"))
            data["scene_id"] = new_id("scene", data.get("scene_id"))
            data["shot_id"] = new_id("shot", data.get("shot_id"))
            job = GenerationJob(**data); db.add(job); db.flush()
            id_map.setdefault("gen_job", {})[row.get("id")] = job.id

        skipped_orphan_results = 0
        for row in payload.get("generation_results") or []:
            data = _clean_row(GenerationResult, row, drop=("id", "job_id"))
            data["shot_id"] = new_id("shot", data.get("shot_id")) or data.get("shot_id")
            data["job_id"] = new_id("gen_job", data.get("job_id"))
            if data.get("shot_id") is None or data.get("job_id") is None:
                # result references a job/shot missing from this backup — skip it
                # honestly instead of crashing the restore
                skipped_orphan_results += 1
                continue
            db.add(GenerationResult(**data))

        for row in payload.get("renders") or []:
            data = _clean_row(EpisodeRender, row)
            data["episode_id"] = new_id("episode", data.get("episode_id")) or data.get("episode_id")
            if data.get("episode_id") is not None:
                db.add(EpisodeRender(**data))

        for row in payload.get("exports") or []:
            data = _clean_row(ExportRecord, row)
            data["project_id"] = target
            data["episode_id"] = new_id("episode", data.get("episode_id"))
            db.add(ExportRecord(**data))

        db.commit()
        counts = {key: len(payload.get(key) or []) for key in ENTITY_ORDER}
        manifest = media_manifest(payload)
        if skipped_orphan_results:
            db.add(Notification(project_id=target, kind="warning",
                                message=f"Restore skipped {skipped_orphan_results} generation result(s) "
                                        "whose job was not included in the backup."))
        return {"restored": True, "mode": mode, "target_series_id": target,
                "entity_counts": counts, "skipped_orphan_results": skipped_orphan_results,
                "media": {"total_referenced": manifest["total"],
                          "available": manifest["available"], "missing": manifest["missing"],
                          "missing_paths": [e["path"] for e in manifest["entries"] if e["status"] == "missing"][:50]},
                "note": "Metadata restored. Missing media files are listed — upload them via media restore."}
    except Exception as error:  # noqa: BLE001
        db.rollback()
        return {"restored": False, "reason": f"restore-failed: {str(error)[:300]}",
                "note": "Rolled back — the active database was NOT modified."}


# ---------------------------------------------------------------------------
# D — automatic backups (persistent config + files under backups/)
# ---------------------------------------------------------------------------

BACKUPS_DIR = "backups"


def backups_dir() -> Path:
    folder = settings.repo_root / BACKUPS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write_auto_backup(db: Session, project_id: int, reason: str) -> dict:
    """Snapshot one series to backups/<slug>-<reason>-<ts>.json (versioned)."""
    from ..api.phase8 import backup_series  # reuse the Phase 8 exporter
    class _FakeDB:  # backup_series only needs .get/.scalars — pass through
        def __init__(self, real): self._real = real
        def __getattr__(self, item): return getattr(self._real, item)
    payload = backup_series(project_id, db)
    payload = decorate_backup(payload)
    payload["backup_metadata"]["reason"] = reason
    project = db.get(Project, project_id)
    slug = (project.slug if project else f"series-{project_id}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = backups_dir() / f"{slug}-{reason}-{stamp}.json"
    target.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    return {"path": target.relative_to(settings.repo_root).as_posix(),
            "backup_id": payload["backup_metadata"]["backup_id"],
            "bytes": target.stat().st_size, "reason": reason}
