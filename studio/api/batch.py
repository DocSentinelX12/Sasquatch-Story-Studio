"""Phase 7 API: batch generation, Production Assistant, storage manager,
queue priorities/retry classification, worker config."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (Asset, AssetVersion, AudioJob, Episode, GenerationJob,
                      GenerationResult, Shot)
from ..providers.registry import ProviderNotConfigured
from ..services import batch as batch_service
from ..services import generation_service
from ..services.storage import sha256_of
from .deps import get_db, row_to_dict

router = APIRouter(prefix="/api/batch", tags=["batch"])


# ==========================================================================
# Batch video + audio
# ==========================================================================

class BatchVideoRequest(BaseModel):
    mode: str = Field(default="missing", pattern="^(missing|failed|rejected|new_versions)$")
    provider_key: str = "auto"
    settings: dict = Field(default_factory=dict)
    episode_id: Optional[int] = None
    scene_id: Optional[int] = None
    shot_ids: Optional[list[int]] = None
    dry_run: bool = False
    auto_prepare: bool = False
    override_warnings: bool = False


@router.post("/video")
def batch_video(payload: BatchVideoRequest, db: Session = Depends(get_db)):
    if payload.dry_run:
        targets = batch_service.batch_targets(
            db, episode_id=payload.episode_id, scene_id=payload.scene_id,
            shot_ids=payload.shot_ids, mode=payload.mode)
        return {"dry_run": True, "target_count": len(targets),
                "targets": [t.shot_ref or t.id for t in targets]}
    try:
        return batch_service.queue_batch_video(
            db, provider_key=payload.provider_key, settings=payload.settings,
            episode_id=payload.episode_id, scene_id=payload.scene_id,
            shot_ids=payload.shot_ids, mode=payload.mode,
            auto_prepare=payload.auto_prepare,
            override_warnings=payload.override_warnings)
    except ProviderNotConfigured as error:
        raise HTTPException(409, {"error": "provider_not_configured",
                                  "message": str(error)}) from error


@router.get("/audio/report/{episode_id}")
def audio_report(episode_id: int, db: Session = Depends(get_db)):
    return batch_service.batch_audio_report(db, episode_id)


class BatchAudioRequest(BaseModel):
    episode_id: int
    include_approved: bool = False
    provider_key: str = "auto"


@router.post("/audio")
def batch_audio(payload: BatchAudioRequest, db: Session = Depends(get_db)):
    try:
        return batch_service.queue_batch_audio(
            db, payload.episode_id, payload.include_approved, payload.provider_key)
    except ProviderNotConfigured as error:
        raise HTTPException(409, {"error": "provider_not_configured",
                                  "message": str(error)}) from error


# ==========================================================================
# Production Assistant (Step 8)
# ==========================================================================

@router.get("/assistant/{episode_id}")
def assistant(episode_id: int, db: Session = Depends(get_db)):
    try:
        return batch_service.production_assistant(db, episode_id)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


# ==========================================================================
# Retry policy classification (Step 12)
# ==========================================================================

@router.get("/retry-policy/{job_id}")
def retry_policy(job_id: int, db: Session = Depends(get_db)):
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return batch_service.retry_allowed(job.attempt, job.error_code)


# ==========================================================================
# Worker configuration (Step 11)
# ==========================================================================

@router.get("/workers")
def workers():
    active = generation_service._get_semaphore()
    used = generation_service._semaphore_size - active._value if hasattr(active, "_value") else None
    return {"configured": generation_service.worker_concurrency(),
            "in_flight_estimate": max(0, generation_service._semaphore_size - active._value)
            if used is not None else None,
            "env_var": "STUDIO_WORKERS",
            "note": "Concurrency is yours to choose — the studio sets no per-video limits."}


# ==========================================================================
# Storage manager (Steps 13–14)
# ==========================================================================

@router.get("/storage")
def storage_report(db: Session = Depends(get_db)):
    def tree_size(folder: Path) -> tuple[int, int]:
        total = count = 0
        if folder.is_dir():
            for path in folder.rglob("*"):
                if path.is_file():
                    try:
                        total += path.stat().st_size
                        count += 1
                    except OSError:
                        pass
        return total, count

    uploads_bytes, uploads_count = tree_size(settings.repo_root / "assets" / "studio-uploads")
    renders_bytes, renders_count = tree_size(settings.repo_root / "renders")
    referenced_paths: set[str] = set()
    for column in (Asset.repo_path, AssetVersion.repo_path, GenerationResult.repo_path):
        for row in db.scalars(select(column)).all():
            if row:
                referenced_paths.add(row)
    for row in db.scalars(select(GenerationResult.repo_path)).all():
        if row:
            referenced_paths.add(row)
    from ..models import AudioRecording, EpisodeRender
    for row in db.scalars(select(AudioRecording.repo_path)).all():
        if row:
            referenced_paths.add(row)
    for row in db.scalars(select(EpisodeRender.output_path)).all():
        if row:
            referenced_paths.add(row)

    orphaned = []
    for folder_name in ("assets/studio-uploads", "renders"):
        base = settings.repo_root / folder_name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() not in (".md",) and "parts-v" not in path.name:
                rel = path.relative_to(settings.repo_root).as_posix()
                if rel not in referenced_paths:
                    try:
                        orphaned.append({"path": rel, "bytes": path.stat().st_size})
                    except OSError:
                        pass
    duplicates = []
    grouped = db.execute(
        select(Asset.sha256, func.count(Asset.id)).where(Asset.sha256.isnot(None))
        .group_by(Asset.sha256).having(func.count(Asset.id) > 1)).all()
    for checksum, count in grouped:
        rows = db.scalars(select(Asset).where(Asset.sha256 == checksum)).all()
        duplicates.append({"sha256": checksum[:12], "count": count,
                           "assets": [{"id": a.id, "title": a.title, "status": a.status} for a in rows]})
    unused = db.scalars(select(Asset).where(
        Asset.status == "obsolete", Asset.episode_id.is_(None))).all()
    return {
        "usage": {
            "uploads": {"bytes": uploads_bytes, "files": uploads_count,
                        "human": _human(uploads_bytes)},
            "renders_and_results": {"bytes": renders_bytes, "files": renders_count,
                                    "human": _human(renders_bytes)},
        },
        "orphaned_files": orphaned[:200],
        "orphaned_bytes": _human(sum(o["bytes"] for o in orphaned)),
        "duplicate_groups": duplicates,
        "unused_assets": [{"id": a.id, "title": a.title} for a in unused[:100]],
        "policy": "Nothing is ever deleted automatically. Cleanup actions are explicit "
                  "and refuse to remove approved or referenced files.",
    }


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


class CleanupRequest(BaseModel):
    paths: list[str] = Field(min_length=1)
    confirm: bool = False


@router.post("/storage/cleanup")
def cleanup(payload: CleanupRequest, db: Session = Depends(get_db)):
    if not payload.confirm:
        raise HTTPException(422, "Set confirm=true to run an explicit cleanup.")
    referenced: set[str] = set()
    for column in (Asset.repo_path, AssetVersion.repo_path, GenerationResult.repo_path):
        for row in db.scalars(select(column)).all():
            if row:
                referenced.add(row)
    from ..models import AudioRecording, EpisodeRender
    for row in db.scalars(select(AudioRecording.repo_path)).all():
        if row:
            referenced.add(row)
    for row in db.scalars(select(EpisodeRender.output_path)).all():
        if row:
            referenced.add(row)
    removed, refused = [], []
    for rel in payload.paths:
        if rel in referenced:
            refused.append({"path": rel, "reason": "referenced by a database record"})
            continue
        target = (settings.repo_root / rel).resolve()
        try:
            target.relative_to(settings.repo_root.resolve())
        except ValueError:
            refused.append({"path": rel, "reason": "outside repository"})
            continue
        if target.is_file() and "parts-v" not in target.name or (target.is_file() and "/renders/episodes/" in rel and "parts-v" in str(target.name)):
            target.unlink(missing_ok=True)
            removed.append(rel)
        elif target.is_file():
            target.unlink(missing_ok=True)
            removed.append(rel)
    return {"removed": removed, "refused": refused,
            "note": "Approved and referenced files are never removed."}


# ==========================================================================
# Duplicate detection on import (Step 14)
# ==========================================================================

class DuplicateCheck(BaseModel):
    sha256: str


@router.post("/storage/duplicate-check")
def duplicate_check(payload: DuplicateCheck, db: Session = Depends(get_db)):
    existing = db.scalars(select(Asset).where(Asset.sha256 == payload.sha256)).all()
    if not existing:
        return {"duplicate": False}
    return {"duplicate": True, "existing": [
        {"id": a.id, "title": a.title, "status": a.status, "repo_path": a.repo_path}
        for a in existing],
        "options": ["use existing", "import anyway", "cancel"]}
