"""Phase 10 Milestone H: video version control service.

Read-only history/compare plus ONE explicit, audited selection action.
Reuses GenerationResult/GenerationJob/Approval exactly — no competing system.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Approval, GenerationJob, GenerationResult, Shot


class VersionControlError(ValueError):
    """Raised for invalid version operations (never silently tolerated)."""


def _stored_checksum(payload) -> str | None:
    """Checksum over ALREADY-STOREED data (prompt/settings) — computed, labelled."""
    if payload is None:
        return None
    try:
        blob = json.dumps(payload, sort_keys=True, default=str).encode()
        return "sha256:" + hashlib.sha256(blob).hexdigest()[:16]
    except (TypeError, ValueError):
        return None


def _rejection_reason(db: Session, result_id: int) -> str | None:
    approval = db.scalar(select(Approval).where(
        Approval.entity_type == "generation_result",
        Approval.entity_id == str(result_id),
        Approval.decision == "rejected").order_by(Approval.id.desc()))
    return approval.note if approval else None


def _version_payload(db: Session, result: GenerationResult, shot: Shot) -> dict:
    job = db.get(GenerationJob, result.job_id) if result.job_id else None
    return {
        "id": result.id,
        "version_number": result.version_number,
        "generation_job_id": result.job_id,
        "attempt": job.attempt if job else None,
        "provider": result.provider_key or (job.provider_key if job else None),
        "provider_model": (result.provider_metadata or {}).get("model"),
        "provider_job_id": job.provider_job_id if job else None,
        "created_at": result.created_at.isoformat() if result.created_at else None,
        "status": result.status,
        "is_approved": bool(result.is_approved),
        "rejection_reason": _rejection_reason(db, result.id) if result.status == "rejected" else None,
        "shot_id": result.shot_id,
        "output_path": result.repo_path,
        "output_uri": result.uri,
        "output_available": bool(result.repo_path),
        "checksum": result.checksum,
        "duration_seconds": result.duration_seconds,
        "resolution": result.resolution,
        "settings": job.settings if job else None,
        "request_checksum_stored": _stored_checksum(job.translated_request) if job else None,
        "is_current_production_version": (
            shot.current_result_id is not None and result.id == shot.current_result_id),
        "test_adapter": bool((result.provider_metadata or {}).get("test_adapter")),
        "metadata_note": "Fields reflect only stored data; nothing fabricated.",
    }


def version_history(db: Session, shot_id: int) -> dict:
    """All versions newest first: results (all statuses) + failed attempts."""
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise VersionControlError(f"Unknown shot {shot_id}")
    results = db.scalars(select(GenerationResult).where(
        GenerationResult.shot_id == shot_id)
        .order_by(GenerationResult.version_number.desc(), GenerationResult.id.desc())).all()
    versions = [_version_payload(db, r, shot) for r in results]
    # failed generation attempts without a result stay visible
    jobs = db.scalars(select(GenerationJob).where(
        GenerationJob.shot_id == shot_id).order_by(GenerationJob.id.desc())).all()
    failed_attempts = [{
        "generation_job_id": j.id, "attempt": j.attempt, "provider": j.provider_key,
        "status": "failed", "error_code": j.error_code, "error": j.error,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "version_number": None, "id": None,
    } for j in jobs if j.status == "failed"]
    current = next((v for v in versions if v["is_current_production_version"]), None)
    return {
        "shot_id": shot_id,
        "shot_ref": shot.shot_ref,
        "current_production_version": current,
        "versions": versions,
        "failed_attempts": failed_attempts,
        "counts": {
            "total_results": len(versions),
            "approved": sum(1 for v in versions if v["status"] == "approved"),
            "rejected": sum(1 for v in versions if v["status"] == "rejected"),
            "needs_review": sum(1 for v in versions if v["status"] == "needs_review"),
            "failed_attempts": len(failed_attempts),
        },
    }


def version_detail(db: Session, shot_id: int, version_id: int) -> dict:
    shot = db.get(Shot, shot_id)
    result = db.get(GenerationResult, version_id)
    if shot is None:
        raise VersionControlError(f"Unknown shot {shot_id}")
    if result is None or result.shot_id != shot_id:
        raise VersionControlError(
            f"Version {version_id} does not belong to shot {shot_id} (cross-shot selection rejected)")
    return _version_payload(db, result, shot)


def compare_versions(db: Session, shot_id: int, a_id: int, b_id: int) -> dict:
    """Only real stored differences — no invented visual/semantic analysis."""
    a = version_detail(db, shot_id, a_id)
    b = version_detail(db, shot_id, b_id)
    fields = ("provider", "provider_model", "status", "is_approved", "rejection_reason",
              "settings", "request_checksum_stored", "checksum", "created_at",
              "duration_seconds", "resolution", "output_path", "attempt")
    differences = []
    for field in fields:
        if a.get(field) != b.get(field):
            differences.append({"field": field, "version_a": a.get(field), "version_b": b.get(field)})
    return {
        "shot_id": shot_id, "version_a": {"id": a_id, "version_number": a["version_number"]},
        "version_b": {"id": b_id, "version_number": b["version_number"]},
        "differences": differences,
        "identical_fields": [f for f in fields if a.get(f) == b.get(f)],
        "note": "Only stored metadata is compared; no visual/semantic analysis exists.",
    }


def select_current_version(db: Session, shot_id: int, version_id: int,
                           note: str | None = None) -> dict:
    """EXPLICIT selection of an APPROVED version as the production version.

    Refuses: failed/rejected/unapproved versions, cross-shot versions,
    missing outputs. Audited via the existing Approval ledger. Never deletes
    or mutates any historical version.
    """
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise VersionControlError(f"Unknown shot {shot_id}")
    result = db.get(GenerationResult, version_id)
    if result is None or result.shot_id != shot_id:
        raise VersionControlError("Cross-shot or unknown version selection rejected")
    if result.status != "approved" or not result.is_approved:
        raise VersionControlError(
            f"Version {version_id} has status '{result.status}' — only explicitly "
            "approved versions can become the production version")
    if not result.repo_path:
        raise VersionControlError("Version has no stored output reference")
    previous = shot.current_result_id
    shot.current_result_id = version_id
    db.add(Approval(
        entity_type="shot_version_selection", entity_id=str(shot_id),
        decision="approved",
        note=(note or "") + f" production version -> result #{version_id}"
        + (f" (was #{previous})" if previous else ""),
    ))
    db.commit()
    db.refresh(shot)
    return {
        "shot_id": shot_id, "selected_version_id": version_id,
        "previous_version_id": previous,
        "version": version_detail(db, shot_id, version_id),
        "note": "Selection only — no version was modified, deleted, or approved anew.",
    }


def version_safety_check(db: Session, shot_id: int | None = None) -> dict:
    """Integrity checks over version storage. Read-only."""
    query = select(GenerationResult)
    if shot_id is not None:
        query = query.where(GenerationResult.shot_id == shot_id)
    results = db.scalars(query).all()
    issues = []
    seen: dict[tuple[int, int], int] = {}
    for result in results:
        key = (result.shot_id or 0, result.version_number)
        seen[key] = seen.get(key, 0) + 1
        if result.status == "approved" and not result.repo_path:
            issues.append({"type": "approved_missing_output",
                           "result_id": result.id, "detail": "approved version has no output path"})
        shot = db.get(Shot, result.shot_id) if result.shot_id else None
        if shot is not None and shot.current_result_id == result.id and result.status != "approved":
            issues.append({"type": "invalid_current_selection",
                           "result_id": result.id, "detail": f"current version has status {result.status}"})
    duplicates = [{"shot_id": s, "version_number": v, "count": c}
                  for (s, v), c in seen.items() if c > 1]
    if duplicates:
        issues.append({"type": "duplicate_version_numbers", "detail": duplicates})
    return {"issues": issues, "results_checked": len(results),
            "clean": not issues,
            "note": "Read-only integrity check; nothing modified."}
