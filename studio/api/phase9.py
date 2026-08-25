"""Phase 9 API: backup verify/upload/restore, media restore, automatic backup
config, and signed generation webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import env, settings
from ..models import GenerationJob, GenerationResult, Notification, Project
from ..providers.registry import DEFINITIONS
from ..services import backup as backup_service
from ..services import generation_service
from .deps import get_db, row_to_dict

router = APIRouter(prefix="/api", tags=["phase9"])


# ==========================================================================
# C — verify backup (checksum + structure), no DB writes
# ==========================================================================

async def _read_backup_file(file: UploadFile) -> dict:
    raw = await file.read()
    if not raw:
        raise HTTPException(422, "Empty file")
    if len(raw) > 200 * 1024 * 1024:
        raise HTTPException(422, "Backup larger than 200MB")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(422, f"Malformed JSON: {str(error)[:200]}") from error
    if not isinstance(payload, dict):
        raise HTTPException(422, "Backup is not a JSON object")
    payload["_uploaded_bytes"] = len(raw)
    payload["_uploaded_sha256"] = hashlib.sha256(raw).hexdigest()
    return payload


@router.post("/backups/verify")
async def verify_backup(file: UploadFile = File(...)):
    """Verify checksum + structure without touching the database."""
    payload = await _read_backup_file(file)
    uploaded = payload.pop("_uploaded_bytes")
    payload.pop("_uploaded_sha256")
    meta = payload.get("backup_metadata") or {}
    validation = backup_service.validate_backup(payload)
    return {"validation": validation,
            "backup_metadata": {k: meta.get(k) for k in
                                ("backup_id", "created_at", "studio_version",
                                 "backup_schema_version", "entity_counts")},
            "bytes": uploaded,
            "checksum_field_present": bool(meta.get("checksum")),
            "note": "Verification only — nothing was restored."}


# ==========================================================================
# A/B — staged restore: upload → validate → preview → confirm
# ==========================================================================

class RestoreRequest(BaseModel):
    mode: str = Field(default="new_series", pattern="^(new_series|into_existing|replace)$")
    target_series_id: Optional[int] = None
    new_series_name: Optional[str] = None
    confirm: bool = False
    auto_snapshot: bool = True


_restore_staging: dict[str, dict] = {}   # token -> {payload, validation}


@router.post("/backups/restore/preview")
async def restore_preview(file: UploadFile = File(...)):
    """Upload + validate + preview. NOTHING is restored until /confirm."""
    payload = await _read_backup_file(file)
    payload.pop("_uploaded_bytes", None)
    payload.pop("_uploaded_sha256", None)
    validation = backup_service.validate_backup(payload)
    manifest = backup_service.media_manifest(payload)
    token = None
    if validation["valid"]:
        import secrets as _secrets
        token = _secrets.token_hex(16)
        _restore_staging[token] = {"payload": payload, "validation": validation,
                                   "received_at": time.time()}
    series = payload.get("series") or {}
    return {"token": token, "validation": validation,
            "series_name": series.get("name"),
            "entity_counts": backup_service.entity_counts(payload),
            "media": {"available": manifest["available"], "missing": manifest["missing"],
                      "missing_paths": [e["path"] for e in manifest["entries"]
                                        if e["status"] == "missing"][:30]},
            "note": "Nothing restored yet. POST /backups/restore/confirm with the token."}


@router.post("/backups/restore/confirm")
def restore_confirm(request: RestoreRequest, token: str, db: Session = Depends(get_db)):
    staging = _restore_staging.get(token)
    if staging is None:
        raise HTTPException(404, "Unknown or expired staging token — upload again")
    if time.time() - staging["received_at"] > 30 * 60:
        _restore_staging.pop(token, None)
        raise HTTPException(410, "Staging token expired — upload again")
    if not request.confirm:
        raise HTTPException(422, "confirm=true required to restore")
    if request.mode in ("into_existing", "replace") and request.target_series_id is None:
        raise HTTPException(422, "target_series_id required for this mode")
    if request.mode == "replace":
        target = db.get(Project, request.target_series_id)
        if target is None:
            raise HTTPException(404, "Target series not found")
        if request.new_series_name is None and target.name:
            raise HTTPException(422, "Replace mode requires explicit new_series_name "
                                     "confirmation text matching nothing (typed confirm)")
    # D — automatic snapshot before a major restore
    snapshot = None
    if request.auto_snapshot and request.target_series_id:
        snapshot = backup_service.write_auto_backup(db, request.target_series_id, "pre-restore")
    payload = staging["payload"]
    result = backup_service.restore_backup(db, payload, request.mode,
                                           request.target_series_id,
                                           request.new_series_name)
    if result.get("restored"):
        _restore_staging.pop(token, None)
        db.add(Notification(project_id=result.get("target_series_id"),
                            kind="info",
                            message=f"Series restored from backup ({request.mode})."
                                    + (f" Snapshot: {snapshot['path']}" if snapshot else "")))
        db.commit()
    result["pre_restore_snapshot"] = snapshot
    return result


# ==========================================================================
# Media restore (upload assets/renders/audio separately)
# ==========================================================================

_SAFE_PATH = re.compile(r"^(assets|renders|audio)/[A-Za-z0-9._/-]+$")


@router.post("/backups/restore/media")
async def restore_media(file: UploadFile = File(...)):
    """Upload a zip containing assets/ and/or renders/ paths. Only safe paths
    inside the repository are extracted; everything else is refused."""
    raw = await file.read()
    if not raw.startswith(b"PK"):
        raise HTTPException(422, "Expected a zip archive")
    restored, skipped, errors = [], [], []
    with zipfile.ZipFile(__import__("io").BytesIO(raw)) as archive:
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            clean = name.removeprefix("./")
            if not _SAFE_PATH.match(clean):
                skipped.append({"path": name, "reason": "path outside assets/renders/audio"})
                continue
            target = (settings.repo_root / clean).resolve()
            try:
                target.relative_to(settings.repo_root.resolve())
            except ValueError:
                skipped.append({"path": name, "reason": "resolves outside repository"})
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
                restored.append(clean)
            except OSError as error:
                errors.append({"path": name, "reason": str(error)[:120]})
    return {"restored": restored, "skipped": skipped, "errors": errors,
            "note": "Media files placed at their original paths; metadata already points at them."}


# ==========================================================================
# D — automatic backups
# ==========================================================================

class AutoBackupConfig(BaseModel):
    enabled: bool = False
    cadence: str = Field(default="weekly", pattern="^(daily|weekly)$")
    project_id: Optional[int] = None


class SystemSetting(BaseModel):
    key: str
    value: dict


def _load_setting(db: Session, key: str) -> dict | None:
    from sqlalchemy import text
    row = db.execute(text("SELECT value_json FROM system_settings WHERE key = :k"),
                     {"k": key}).first()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return None


def _save_setting(db: Session, key: str, value: dict) -> None:
    from sqlalchemy import text
    db.execute(text(
        "INSERT INTO system_settings (key, value_json, updated_at) "
        "VALUES (:k, :v, :t) ON CONFLICT(key) DO UPDATE SET value_json=:v, updated_at=:t"),
        {"k": key, "v": json.dumps(value), "t": datetime.now(timezone.utc).isoformat()})
    db.commit()


AUTO_BACKUP_KEY = "auto_backup"


@router.get("/backups/auto")
def get_auto_backup_config(db: Session = Depends(get_db)):
    config = _load_setting(db, AUTO_BACKUP_KEY) or {"enabled": False, "cadence": "weekly"}
    files = sorted(backup_service.backups_dir().glob("*.json"))
    history = [{"path": f.relative_to(settings.repo_root).as_posix(),
                "bytes": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()}
               for f in files[-20:]]
    return {"config": config, "history": history,
            "note": "Optional. 'Before restore' snapshots always happen unless disabled."}


@router.post("/backups/auto")
def set_auto_backup_config(payload: AutoBackupConfig, db: Session = Depends(get_db)):
    _save_setting(db, AUTO_BACKUP_KEY, payload.model_dump())
    return {"config": payload.model_dump()}


@router.post("/backups/auto/run")
def run_auto_backup(project_id: Optional[int] = None, reason: str = "manual",
                    db: Session = Depends(get_db)):
    target = project_id
    if target is None:
        project = db.scalar(select(Project).order_by(Project.id))
        if project is None:
            raise HTTPException(404, "No series to back up")
        target = project.id
    return backup_service.write_auto_backup(db, target, reason)


def auto_backup_due(db: Session) -> bool:
    config = _load_setting(db, AUTO_BACKUP_KEY) or {}
    if not config.get("enabled"):
        return False
    files = sorted(backup_service.backups_dir().glob("*.json"))
    if not files:
        return True
    newest = datetime.fromtimestamp(files[-1].stat().st_mtime, timezone.utc)
    age_days = (datetime.now(timezone.utc) - newest).total_seconds() / 86400
    return age_days >= (1 if config.get("cadence") == "daily" else 7)


# ==========================================================================
# E — signed generation webhooks
# ==========================================================================

WEBHOOK_SECRET_ENV = "STUDIO_WEBHOOK_SECRET"
REPLAY_WINDOW_SECONDS = 10 * 60


def _provider_transports() -> dict:
    transports = {}
    for key, definition in DEFINITIONS.items():
        if definition.kind != "video":
            continue
        # Honest per-provider transport: every verified cloud contract in this
        # build is asynchronous task POLLING. Our own Local Video Server
        # contract may optionally call back (webhook) — both supported.
        transports[key] = "both" if key == "local" else "polling"
    return transports


@router.get("/webhooks/transports")
def webhook_transports():
    return {"transports": _provider_transports(),
            "secret_env": WEBHOOK_SECRET_ENV if env(WEBHOOK_SECRET_ENV) else None,
            "note": "Cloud providers (Seedance/Veo/Wan) use polling per their "
                    "verified contracts. The Local Video Server contract supports "
                    "an optional signed webhook in addition to polling."}


@router.post("/webhooks/generation")
async def generation_webhook(request: __import__("fastapi").Request,
                             db: Session = Depends(get_db)):
    """Signed webhook receiver. HMAC-SHA256 over the RAW body using
    STUDIO_WEBHOOK_SECRET; the signature is verified BEFORE the body is parsed
    or any database access happens. Timestamps within the replay window when
    present. Provider status is never trusted blindly: a 'succeeded' webhook
    only records a hint — polling still verifies and downloads the result."""
    secret = env(WEBHOOK_SECRET_ENV)
    if not secret:
        raise HTTPException(409, {"error": "webhook_not_configured",
                                  "message": f"Set {WEBHOOK_SECRET_ENV} to enable webhooks."})
    raw_body = await request.body()
    signature = request.headers.get("x-signature")
    if not signature:
        raise HTTPException(401, "Missing X-Signature header")
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Invalid signature")
    try:
        event_data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(422, f"Malformed JSON: {str(error)[:120]}") from error
    from .phase9_schemas import WebhookEvent
    try:
        event = WebhookEvent(**event_data)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(422, f"Invalid event: {str(error)[:160]}") from error
    timestamp_header = request.headers.get("x-timestamp")
    if timestamp_header:
        try:
            sent_at = datetime.fromisoformat(timestamp_header.replace("Z", "+00:00"))
            age = abs(datetime.now(timezone.utc) - sent_at).total_seconds()
            if age > REPLAY_WINDOW_SECONDS:
                raise HTTPException(401, f"Replay window exceeded ({int(age)}s old)")
        except ValueError as error:
            raise HTTPException(401, "Malformed timestamp") from error

    job = db.scalar(select(GenerationJob).where(
        GenerationJob.provider_key == event.provider,
        GenerationJob.provider_job_id == event.job_id))
    if job is None:
        raise HTTPException(404, f"No {event.provider} job {event.job_id}")

    normalized = {"succeeded": "generating",  # polling verifies + downloads
                  "running": "generating",
                  "failed": "failed",
                  "cancelled": "cancelled"}.get(event.status)
    if normalized is None:
        raise HTTPException(422, f"Unrecognized status '{event.status}'")

    result = {"job_id": job.id, "provider": event.provider,
              "provider_status": event.status, "normalized": normalized}
    if event.status == "failed":
        job.status = "failed"
        job.error_code = "generation_failed"
        job.error = (event.error or "provider reported failure")[:400]
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        result["note"] = "Job marked failed from signed webhook."
    elif event.status == "succeeded":
        # Do NOT trust success blindly: keep polling (worker or manual) to fetch
        # and verify the result file. Record the hint.
        job.poll_metadata = {**(job.poll_metadata or {}),
                             "webhook_hint": {"video_url": event.video_url,
                                              "at": datetime.now(timezone.utc).isoformat()}}
        db.commit()
        result["note"] = "Hint recorded — polling still verifies and downloads the result."
    else:
        job.status = normalized
        db.commit()
        result["note"] = "Status updated from signed webhook."


    return result
