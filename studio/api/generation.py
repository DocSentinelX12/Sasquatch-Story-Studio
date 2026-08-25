"""Phase 5 generation API: providers, jobs, results, review.

Every endpoint is honest: unconfigured providers report provider_not_configured
with the missing env var NAMES; no results are fabricated.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..config import env, settings
from ..models import GenerationJob, GenerationResult, Shot
from ..providers import adapters as adapter_factory
from ..providers import health
from ..providers.registry import (
    DEFINITIONS,
    ProviderApiError,
    ProviderAuthError,
    ProviderNotConfigured,
    provider_status_list,
)
from ..services import generation_service as service
from ..services.storage import resolve_repo_path
from .deps import get_db, row_to_dict

router = APIRouter(prefix="/api", tags=["generation"])


# ==========================================================================
# Providers (PART 1, 2, 3)
# ==========================================================================

@router.get("/providers")
def list_providers():
    """Status + capabilities. 'connected' only after a real validation call.
    Credential values are never included."""
    return {"providers": provider_status_list()}


@router.post("/providers/{key}/validate")
def validate_provider(key: str):
    """Run a REAL connection validation (free endpoint, no generation)."""
    definition = DEFINITIONS.get(key)
    if definition is None:
        raise HTTPException(404, "Unknown provider")
    try:
        adapter = adapter_factory.get_video_adapter(key)
    except ProviderNotConfigured as error:
        health.record_validation(key, "not_configured", str(error))
        raise HTTPException(409, {"error": "provider_not_configured",
                                  "message": str(error)}) from error
    try:
        status_value = adapter.validate_connection()
    except ProviderAuthError as error:
        status_value = "auth_error"
        health.record_validation(key, status_value, str(error))
    except ProviderApiError as error:
        status_value = "api_error"
        health.record_validation(key, status_value, str(error))
    else:
        health.record_validation(key, status_value, "" if status_value == "connected" else status_value)
    return {"key": key, "status": status_value,
            "connected": status_value == "connected"}


@router.post("/generation/select-provider")
def select_provider(payload: dict, db: Session = Depends(get_db)):
    """Recommend a provider for a shot (automatic mode) without cost claims."""
    shot_id = payload.get("shot_id")
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(404, "Shot not found")
    package = service.build_generation_package(db, shot)
    resolved, errors = service.resolve_provider(payload.get("provider_key") or "auto",
                                                package, payload.get("settings") or {})
    return {"provider": resolved or None, "errors": errors,
            "caps": service.provider_caps(resolved).as_dict() if resolved else None}


# ==========================================================================
# Jobs (PART 9, 10, 11)
# ==========================================================================

class GenerateRequest(BaseModel):
    provider_key: str = "auto"
    settings: dict = Field(default_factory=dict)


@router.post("/shots/{shot_id}/generate", status_code=201)
def create_generation_job(shot_id: int, payload: GenerateRequest, db: Session = Depends(get_db)):
    """Create a DRAFT job (translate + validate, no submission yet)."""
    try:
        job = service.create_job(db, shot_id, payload.provider_key, payload.settings)
    except ProviderNotConfigured as error:
        raise HTTPException(409, {"error": "provider_not_configured",
                                  "message": str(error)}) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except PermissionError as error:
        raise HTTPException(409, str(error)) from error
    return job_payload(db, job)


@router.get("/shots/{shot_id}/preview-request")
def preview_request(shot_id: int, provider_key: str = "auto", settings: Optional[str] = None,
                    db: Session = Depends(get_db)):
    """Exact provider-translated request preview — nothing is submitted (PART 18)."""
    import json as _json
    try:
        parsed = _json.loads(settings) if settings else {}
    except ValueError:
        raise HTTPException(422, "settings must be a JSON object")
    preview = service.translate_preview(db, shot_id, provider_key, parsed)
    return preview


@router.get("/generation/jobs")
def list_jobs(
    status: Optional[str] = None,
    shot_id: Optional[int] = None,
    provider_key: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = select(GenerationJob)
    if status:
        query = query.where(GenerationJob.status == status)
    if shot_id:
        query = query.where(GenerationJob.shot_id == shot_id)
    if provider_key:
        query = query.where(GenerationJob.provider_key == provider_key)
    jobs = db.scalars(query.order_by(GenerationJob.id.desc()).limit(min(limit, 500))).all()
    counts = dict(db.execute(
        select(GenerationJob.status, func.count(GenerationJob.id)).group_by(GenerationJob.status)
    ).all())
    return {"jobs": [job_payload(db, job, include_request=False) for job in jobs],
            "counts_by_status": counts}


def job_payload(db: Session, job: GenerationJob, include_request: bool = True) -> dict:
    result = db.scalar(select(GenerationResult).where(GenerationResult.job_id == job.id))
    shot = db.get(Shot, job.shot_id) if job.shot_id else None
    data = {
        **row_to_dict(job),
        "shot_ref": shot.shot_ref if shot else None,
        "result_id": result.id if result else None,
        "result_status": result.status if result else None,
    }
    data.pop("prompt_package", None)  # heavy; use preview endpoints
    if include_request:
        data["translated_request"] = job.translated_request
        data["references_report"] = job.submitted_references
    return data


@router.get("/generation/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    data = row_to_dict(job)
    data.pop("prompt_package", None)  # heavy; use preview endpoints
    return data


@router.post("/generation/jobs/{job_id}/submit")
def submit(job_id: int, db: Session = Depends(get_db)):
    try:
        job = service.submit_job(job_id)
    except (ValueError, PermissionError) as error:
        raise HTTPException(409, str(error)) from error
    return row_to_dict(job)


@router.post("/generation/jobs/{job_id}/cancel")
def cancel(job_id: int, db: Session = Depends(get_db)):
    try:
        job = service.cancel_job(db, job_id)
    except (ValueError, PermissionError) as error:
        raise HTTPException(409, str(error)) from error
    return row_to_dict(job)


class RetryRequest(BaseModel):
    provider_key: Optional[str] = None
    settings_overrides: Optional[dict] = None


@router.post("/generation/jobs/{job_id}/retry", status_code=201)
def retry(job_id: int, payload: RetryRequest, db: Session = Depends(get_db)):
    """Retry creates a NEW attempt; the previous attempt is preserved."""
    try:
        job = service.retry_job(db, job_id, payload.provider_key, payload.settings_overrides)
    except ProviderNotConfigured as error:
        raise HTTPException(409, {"error": "provider_not_configured", "message": str(error)}) from error
    except (ValueError, PermissionError) as error:
        raise HTTPException(409 or 422, str(error)) from error
    return row_to_dict(job)


# ==========================================================================
# Results + review (PART 15, 16, 17)
# ==========================================================================

@router.get("/generation/results")
def list_results(shot_id: Optional[int] = None, status: Optional[str] = None,
                 db: Session = Depends(get_db)):
    query = select(GenerationResult)
    if shot_id:
        query = query.where(GenerationResult.shot_id == shot_id)
    if status:
        query = query.where(GenerationResult.status == status)
    results = db.scalars(query.order_by(GenerationResult.id.desc())).all()
    payload = []
    for result in results:
        job = db.get(GenerationJob, result.job_id)
        shot = db.get(Shot, result.shot_id) if result.shot_id else None
        payload.append({
            **row_to_dict(result),
            "shot_ref": shot.shot_ref if shot else None,
            "job_status": job.status if job else None,
            "test_adapter": (result.provider_metadata or {}).get("test_adapter", False),
        })
    return {"results": payload}


@router.get("/generation/results/{result_id}/file")
def result_file(result_id: int, db: Session = Depends(get_db)):
    result = db.get(GenerationResult, result_id)
    if result is None or not result.repo_path:
        raise HTTPException(404, "Result file not available")
    path = resolve_repo_path(result.repo_path)
    if path is None:
        raise HTTPException(404, "Result file missing on disk")
    return FileResponse(path, media_type="video/mp4",
                        filename=path.name)


class ReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: Optional[str] = None


@router.post("/generation/results/{result_id}/review")
def review(result_id: int, payload: ReviewRequest, db: Session = Depends(get_db)):
    try:
        result = service.review_result(db, result_id, payload.decision, payload.reason)
    except PermissionError as error:
        raise HTTPException(422, str(error)) from error
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    return row_to_dict(result)
