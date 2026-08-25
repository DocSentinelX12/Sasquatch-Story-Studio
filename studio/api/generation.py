"""Provider status + generation job endpoints.

The queue is a real job ledger. No provider is connected in Phase 1, so moving
a job to `queued` is only allowed when the provider is genuinely configured —
otherwise the API returns a structured, honest error. Nothing is ever faked.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import GenerationJob, GenerationResult, MediaKind
from ..providers.adapters import get_adapter
from ..providers.base import GenerationRequest
from ..providers.registry import DEFINITIONS, ProviderNotConfigured, provider_status_list
from .deps import get_db, row_to_dict, slugify  # noqa: F401

router = APIRouter(prefix="/api", tags=["generation"])

JOB_STATUSES = {
    "draft", "queued", "generating", "completed", "failed",
    "needs_review", "approved", "rejected", "cancelled",
}


class JobCreate(BaseModel):
    project_id: Optional[int] = None
    episode_id: Optional[int] = None
    scene_id: Optional[int] = None
    shot_id: Optional[int] = None
    provider_key: Optional[str] = None
    media_kind: str = "video"
    title: str = ""
    prompt_package: Optional[dict] = None   # {positive_prompt, negative_constraints, reference_images, continuity_notes}
    settings: Optional[dict] = None


class JobAction(BaseModel):
    note: Optional[str] = None


@router.get("/providers")
def list_providers():
    """Provider status. Reports env var NAMES only — never credential values."""
    return {"providers": provider_status_list()}


@router.get("/generation/jobs")
def list_jobs(
    status: Optional[str] = None,
    project_id: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    if status is not None and status not in JOB_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(JOB_STATUSES)}")
    query = select(GenerationJob)
    if status:
        query = query.where(GenerationJob.status == status)
    if project_id:
        query = query.where(GenerationJob.project_id == project_id)
    jobs = db.scalars(query.order_by(GenerationJob.id.desc()).limit(min(limit, 500))).all()
    counts = dict(
        db.execute(select(GenerationJob.status, func.count(GenerationJob.id)).group_by(GenerationJob.status)).all()
    )
    return {
        "jobs": [
            {**row_to_dict(j), "result_count": len(j.results)} for j in jobs
        ],
        "counts_by_status": counts,
    }


@router.post("/generation/jobs", status_code=201)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    if payload.provider_key is not None and payload.provider_key not in DEFINITIONS:
        raise HTTPException(422, f"Unknown provider '{payload.provider_key}'. Known: {sorted(DEFINITIONS)}")
    if payload.media_kind not in {m.value for m in MediaKind}:
        raise HTTPException(422, "media_kind must be video | image | animation_test")
    job = GenerationJob(
        project_id=payload.project_id,
        episode_id=payload.episode_id,
        scene_id=payload.scene_id,
        shot_id=payload.shot_id,
        provider_key=payload.provider_key,
        media_kind=payload.media_kind,
        status="draft",
        title=payload.title,
        prompt_package=payload.prompt_package,
        settings=payload.settings,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return row_to_dict(job)


@router.get("/generation/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    results = db.scalars(
        select(GenerationResult).where(GenerationResult.job_id == job_id).order_by(GenerationResult.version_number)
    ).all()
    return {**row_to_dict(job), "results": [row_to_dict(r) for r in results]}


@router.post("/generation/jobs/{job_id}/queue")
def queue_job(job_id: int, db: Session = Depends(get_db)):
    """Move a draft/failed job to queued — only if its provider is truly configured."""
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status not in ("draft", "failed"):
        raise HTTPException(409, f"Cannot queue a job in status '{job.status}' (only draft or failed)")
    if not job.provider_key:
        raise HTTPException(422, "Job has no provider selected")

    definition = DEFINITIONS.get(job.provider_key)
    adapter = get_adapter(job.provider_key)
    if definition is None or adapter is None:
        raise HTTPException(422, f"Unknown provider '{job.provider_key}'")

    # Build the normalized request for validation only (no network calls).
    package = job.prompt_package or {}
    request = GenerationRequest(
        request_id=f"job-{job.id}",
        episode_id=str(job.episode_id or ""),
        scene_id=str(job.scene_id or ""),
        shot_id=str(job.shot_id or ""),
        media_kind=MediaKind(job.media_kind),
        duration_seconds=float((job.settings or {}).get("duration_seconds", 6.0)),
        aspect_ratio=(job.settings or {}).get("aspect_ratio", "16:9"),
        positive_prompt={"main": package.get("positive_prompt", "")},
        negative_constraints=tuple(package.get("negative_constraints", [])),
    )
    errors = list(adapter.validate(request))
    missing_env = definition.missing_env()
    if missing_env:
        job.error = ProviderNotConfigured(job.provider_key, missing_env).args[0]
        db.commit()
        raise HTTPException(
            409,
            detail={
                "error": "provider_not_configured",
                "provider": job.provider_key,
                "missing_env": missing_env,
                "message": job.error,
                "hint": "Add the listed environment variables to the server-side .env file and restart the studio.",
            },
        )
    if errors:
        job.error = "Validation failed: " + "; ".join(errors)
        db.commit()
        raise HTTPException(422, {"error": "invalid_request", "errors": errors})

    # Credentials present but no real adapter in Phase 1 → honest refusal.
    from ..providers.registry import AdapterNotImplemented

    job.error = AdapterNotImplemented(job.provider_key).args[0]
    db.commit()
    raise HTTPException(
        501,
        detail={
            "error": "adapter_not_implemented",
            "provider": job.provider_key,
            "message": job.error,
            "hint": "The provider interface, configuration and job architecture are ready; the live adapter ships in a later phase.",
        },
    )


@router.post("/generation/jobs/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status not in ("failed", "rejected"):
        raise HTTPException(409, f"Cannot retry a job in status '{job.status}'")
    job.status = "draft"
    job.error = None
    db.commit()
    db.refresh(job)
    return row_to_dict(job)


@router.post("/generation/jobs/{job_id}/cancel")
def cancel_job(job_id: int, payload: JobAction | None = None, db: Session = Depends(get_db)):
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status in ("completed", "approved", "cancelled"):
        raise HTTPException(409, f"Cannot cancel a job in status '{job.status}'")
    job.status = "cancelled"
    if payload and payload.note:
        job.error = payload.note
    db.commit()
    db.refresh(job)
    return row_to_dict(job)


@router.post("/generation/jobs/{job_id}/review")
def review_job(job_id: int, decision: str, note: Optional[str] = None, db: Session = Depends(get_db)):
    """Record an explicit review decision (approval-first workflow)."""
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if decision not in ("needs_review", "approved", "rejected"):
        raise HTTPException(422, "decision must be needs_review | approved | rejected")
    job.status = decision
    db.commit()
    db.refresh(job)
    return row_to_dict(job)
