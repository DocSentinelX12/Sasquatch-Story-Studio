"""Phase 5 generation service: queue orchestration, async workers, results.

Flow: create job (draft) → translate + preview → submit (background thread)
→ poll provider → download result → versioned result row (needs_review).
No fake results: unconfigured providers fail with provider_not_configured.
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import GenerationJob, GenerationResult, Shot
from ..providers import adapters as adapter_factory
from ..providers.capabilities import ProviderCapabilities
from ..providers.registry import (
    DEFINITIONS,
    ProviderApiError,
    ProviderAuthError,
    ProviderNotConfigured,
)
from .shot_package import build_generation_package

MAX_POLL_SECONDS = 20 * 60
POLL_INTERVAL = 8.0

JOB_STATUSES = {
    "draft", "queued", "submitting", "submitted", "generating", "completed",
    "failed", "cancelled", "needs_review", "approved", "rejected",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_get_episode(db: Session, episode_id: int | None):
    if episode_id is None:
        return None
    from ..models import Episode
    return db.get(Episode, episode_id)


# ---------------------------------------------------------------------------
# Provider resolution + capability validation
# ---------------------------------------------------------------------------

def provider_caps(provider_key: str) -> ProviderCapabilities | None:
    definition = DEFINITIONS.get(provider_key)
    return definition.caps if definition else None


def resolve_provider(provider_key: str | None, package: dict, settings: dict) -> tuple[str, list[str]]:
    """Automatic Best Match: pick a configured provider whose declared
    capabilities support the requested shot. No cost/performance claims.

    Examined: image-to-video, text-to-video, reference count, first/last
    frame (continuation), duration, resolution, aspect ratio, audio, and
    current provider availability (credentials present + adapter implemented).
    """
    if provider_key and provider_key != "auto":
        return provider_key, []
    from ..providers.adapters import test_provider_enabled

    errors: list[str] = []
    candidates: list[str] = ["local", "veo", "seedance", "wan"]
    if test_provider_enabled():
        candidates.append("test-echo")
    for key in candidates:
        definition = DEFINITIONS.get(key)
        # availability: credentials present AND an implemented adapter (caps declared)
        if definition is None or definition.caps is None or definition.missing_env():
            continue
        caps_errors = _caps_errors(definition.caps, package, settings)
        if not caps_errors:
            return key, []
        errors.extend(f"{key}: {e}" for e in caps_errors)
    return "", errors or [
        "No video provider is configured. Add credentials for a cloud provider "
        "(GEMINI_API_KEY / SEEDANCE_API_KEY / WAN_API_KEY) or set LOCAL_VIDEO_API_URL "
        "for the self-hosted lane.",
    ]


def _caps_errors(caps: ProviderCapabilities, package: dict, settings: dict) -> list[str]:
    errors = list(caps.validate_settings(settings))
    frames = package.get("frame_references") or {}
    wants_first = bool(frames.get("first_frame") or frames.get("prev_shot_frame"))
    wants_last = bool(frames.get("last_frame") or frames.get("next_shot_frame"))
    if wants_first and not caps.image_to_video:
        errors.append("first-frame conditioning requested but unsupported")
    if wants_last and not (caps.last_frame or caps.start_end_frames):
        errors.append("last-frame conditioning requested but unsupported")
    # reference count vs provider slots
    reference_count = 0
    frames_count = sum(1 for purpose in ("first_frame", "last_frame", "prev_shot_frame",
                                         "next_shot_frame") if frames.get(purpose))
    reference_count += frames_count
    for character in package.get("characters", []):
        reference_count += sum(len(v) for v in (character.get("references") or {}).values())
    if reference_count and not (caps.reference_images or caps.image_to_video or caps.last_frame):
        errors.append(f"{reference_count} reference image(s) requested but provider takes none")
    if settings.get("generate_audio") and not caps.audio_generation:
        errors.append("audio generation requested but unsupported")
    return errors


def validate_for_provider(package: dict, provider_key: str, settings: dict) -> dict:
    """Capability validation + reference prioritization report."""
    caps = provider_caps(provider_key)
    if caps is None:
        return {"ok": False, "errors": [f"Unknown provider '{provider_key}'"],
                "warnings": [], "references": {"submitted": [], "skipped": []}}
    errors = _caps_errors(caps, package, settings)
    warnings: list[str] = []
    submitted, skipped = prioritize_references(package, caps)
    for entry in skipped:
        warnings.append(f"Reference not submitted to {provider_key}: {entry['reason']}")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "references": {"submitted": submitted, "skipped": skipped}}


def prioritize_references(package: dict, caps: ProviderCapabilities) -> tuple[list, list]:
    """Order references by production priority and respect provider slot limits.

    Priority: first frame > last frame > primary character references >
    expressions > poses > location. Skipped references are recorded, never lost.
    """
    frames = package.get("frame_references") or {}
    queue: list[tuple[str, int, dict]] = []

    def add(purpose: str, priority: int):
        for entry in frames.get(purpose) or []:
            queue.append((purpose, priority, entry))

    add("first_frame", 0)
    add("last_frame", 1)
    add("prev_shot_frame", 2)
    add("next_shot_frame", 3)
    for character in package.get("characters", []):
        for group, priority in (("primary", 4), ("expression", 5), ("pose", 6)):
            for entry in (character.get("references") or {}).get(group, []):
                queue.append((f"character:{character.get('name')}:{group}", priority, entry))
    for entry in frames.get("location_reference") or []:
        queue.append(("location", 7, entry))
    for entry in frames.get("storyboard_image") or []:
        queue.append(("storyboard_image", 8, entry))

    queue.sort(key=lambda item: item[1])
    slots = caps.max_reference_slots if caps.max_reference_slots else 0
    submitted: list[dict] = []
    skipped: list[dict] = []
    for purpose, _priority, entry in queue:
        path = entry.get("path") or ""
        record = {"purpose": purpose, "reference_id": entry.get("reference_id"),
                  "asset_id": entry.get("asset_id"), "path": path,
                  "label": entry.get("label")}
        if caps.url_reference_only and not path.startswith(("http://", "https://")):
            skipped.append({**record, "reason": "provider requires public URLs for reference images"})
            continue
        if slots and len(submitted) >= slots:
            skipped.append({**record, "reason": f"provider reference limit ({slots}) reached"})
            continue
        submitted.append(record)
    return submitted, skipped


# ---------------------------------------------------------------------------
# Job creation / translation preview
# ---------------------------------------------------------------------------

def create_job(db: Session, shot_id: int, provider_key: str, settings: dict) -> GenerationJob:
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise ValueError("Shot not found")
    allowed = ("ready_for_generation", "generating", "generated", "needs_revision", "complete")
    if shot.status not in allowed:
        raise PermissionError(
            f"Shot status is '{shot.status}' — must be one of {allowed} "
            "(approve the shot first if needed)")
    package = build_generation_package(db, shot)
    resolved, errors = resolve_provider(provider_key, package, settings)
    if not resolved:
        raise ProviderNotConfigured("auto", errors)
    caps_check = validate_for_provider(package, resolved, settings)
    if caps_check["errors"]:
        raise ValueError("; ".join(caps_check["errors"]))
    adapter = adapter_factory.get_video_adapter(resolved)
    translated = adapter.translate(package["prompt_package"], settings)
    attempt = (db.scalar(select(func.max(GenerationJob.attempt)).where(
        GenerationJob.shot_id == shot_id)) or 0) + 1
    scene = shot.scene
    episode = session_get_episode(db, scene.episode_id if scene else None)
    job = GenerationJob(
        project_id=episode.project_id if episode else None,
        episode_id=scene.episode_id if scene else None,
        scene_id=shot.scene_id, shot_id=shot_id,
        provider_key=resolved, media_kind="video", status="draft",
        title=f"{shot.shot_ref or 'Shot'} — attempt {attempt}",
        prompt_package=package, settings=settings,
        translated_request=translated,
        submitted_references=caps_check["references"],
        attempt=attempt, package_version=package.get("generation_package_version", 1),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def translate_preview(db: Session, shot_id: int, provider_key: str, settings: dict) -> dict:
    """Provider-translated request preview WITHOUT submitting (PART 18)."""
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise ValueError("Shot not found")
    package = build_generation_package(db, shot)
    resolved, errors = resolve_provider(provider_key, package, settings)
    if not resolved:
        return {"provider": None, "errors": errors, "translated": None,
                "capabilities": None, "references": {"submitted": [], "skipped": []}}
    caps = provider_caps(resolved)
    check = validate_for_provider(package, resolved, settings)
    try:
        adapter = adapter_factory.get_video_adapter(resolved)
        translated = adapter.translate(package["prompt_package"], settings)
    except ProviderNotConfigured as error:
        return {"provider": resolved, "errors": [str(error)], "translated": None,
                "capabilities": caps.as_dict() if caps else None,
                "references": check["references"]}
    return {
        "provider": resolved,
        "translated": translated,
        "capabilities": caps.as_dict() if caps else None,
        "references": check["references"],
        "prompt_package": package["prompt_package"],
        "errors": check["errors"], "warnings": check["warnings"],
    }


# ---------------------------------------------------------------------------
# Submission + async worker (PART 10)
# ---------------------------------------------------------------------------

_active_pollers: set[int] = set()
_poller_lock = threading.Lock()

# --- Worker pool (Step 11): configurable concurrency ------------------------
PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
PRIORITY_LABELS = {v: k for k, v in PRIORITY_ORDER.items()}
_semaphore: threading.Semaphore | None = None
_semaphore_size = 0
_worker_lock = threading.Lock()


def worker_concurrency() -> int:
    from ..config import env
    try:
        value = int(env("STUDIO_WORKERS") or 2)
    except (TypeError, ValueError):
        value = 2
    return max(1, min(value, 32))


def _get_semaphore() -> threading.Semaphore:
    global _semaphore, _semaphore_size
    with _worker_lock:
        size = worker_concurrency()
        if _semaphore is None or _semaphore_size != size:
            _semaphore = threading.Semaphore(size)
            _semaphore_size = size
        return _semaphore


def submit_job(job_id: int) -> GenerationJob:
    """Submit synchronously (HTTP call), then hand polling to a worker thread."""
    from ..db import SessionLocal

    session = SessionLocal()
    try:
        job = session.get(GenerationJob, job_id)
        if job is None:
            raise ValueError("Job not found")
        if job.status not in ("draft", "queued"):
            raise PermissionError(f"Cannot submit a job in status '{job.status}'")
        job.status = "submitting"
        job.started_at = datetime.now(timezone.utc)
        session.commit()
        try:
            adapter = adapter_factory.get_video_adapter(job.provider_key)
            translated = job.translated_request or {}
            handle = adapter.submit(translated)
        except ProviderNotConfigured as error:
            job.status = "failed"
            job.error_code = "provider_not_configured"
            job.error = str(error)
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(job)
            return job
        except ProviderAuthError as error:
            job.status = "failed"
            job.error_code = "authentication_failed"
            job.error = str(error)
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(job)
            return job
        except (ProviderApiError, ValueError) as error:
            job.status = "failed"
            job.error_code = "invalid_request" if isinstance(error, ValueError) else "api_error"
            job.error = str(error)
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(job)
            return job
        job.status = "submitted"
        job.provider_job_id = handle.provider_job_id
        job.submitted_at = datetime.now(timezone.utc)
        job.poll_metadata = {"raw_submit": _safe_raw(handle.raw)}
        session.commit()
        session.refresh(job)
    finally:
        session.close()

    _spawn_poller(job_id)
    from ..db import SessionLocal as SL2
    check = SL2()
    try:
        return check.get(GenerationJob, job_id)
    finally:
        check.close()


def _safe_raw(raw) -> dict:
    try:
        import json
        return json.loads(json.dumps(raw or {}, default=str))
    except (TypeError, ValueError):
        return {}


def _spawn_poller(job_id: int) -> None:
    with _poller_lock:
        if job_id in _active_pollers:
            return
        _active_pollers.add(job_id)

    def runner():
        sem = _get_semaphore()
        acquired = sem.acquire(timeout=MAX_POLL_SECONDS)
        try:
            if not acquired:
                _fail_job(job_id, "provider_timeout",
                          f"worker pool busy for over {MAX_POLL_SECONDS // 60} minutes")
                return
            _poll_worker(job_id)
        finally:
            if acquired:
                sem.release()
            with _poller_lock:
                _active_pollers.discard(job_id)

    threading.Thread(target=runner, daemon=True).start()


def _fail_job(job_id: int, code: str, message: str) -> None:
    from ..db import SessionLocal

    session = SessionLocal()
    try:
        job = session.get(GenerationJob, job_id)
        if job and job.status in ("submitted", "generating", "submitting"):
            job.status = "failed"
            job.error_code = code
            job.error = message
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
    finally:
        session.close()


def resume_pending_jobs() -> int:
    """On server boot, resume polling for jobs stuck in submitted/generating."""
    from ..db import SessionLocal

    session = SessionLocal()
    try:
        jobs = session.scalars(select(GenerationJob).where(
            GenerationJob.status.in_(["submitted", "generating", "submitting"]))).all()
        for job in jobs:
            if job.provider_job_id:
                _spawn_poller(job.id)
        return len(jobs)
    finally:
        session.close()


def _poll_worker(job_id: int) -> None:
    from ..db import SessionLocal

    deadline = time.time() + MAX_POLL_SECONDS
    try:
        while time.time() < deadline:
            session = SessionLocal()
            try:
                job = session.get(GenerationJob, job_id)
                if job is None or job.status == "cancelled":
                    return
                try:
                    adapter = adapter_factory.get_video_adapter(job.provider_key)
                    handle = adapter.poll(job.provider_job_id)
                except ProviderAuthError as error:
                    job.status = "failed"; job.error_code = "authentication_failed"
                    job.error = str(error); job.completed_at = datetime.now(timezone.utc)
                    session.commit(); return
                except ProviderApiError as error:
                    job.status = "failed"; job.error_code = "provider_api_error"
                    job.error = str(error); job.completed_at = datetime.now(timezone.utc)
                    session.commit(); return
                if handle.state == "failed":
                    job.status = "failed"
                    job.error_code = "generation_failed"
                    job.error = _extract_error(handle.raw) or "provider reported failure"
                    job.completed_at = datetime.now(timezone.utc)
                    session.commit(); return
                if handle.state == "succeeded":
                    _finalize_result(session, job, adapter)
                    return
                if job.status != handle.state and handle.state in ("submitted", "generating"):
                    job.status = handle.state
                session.commit()
            finally:
                session.close()
            time.sleep(POLL_INTERVAL)
        # timeout
        session = SessionLocal()
        try:
            job = session.get(GenerationJob, job_id)
            if job and job.status in ("submitted", "generating"):
                job.status = "failed"
                job.error_code = "provider_timeout"
                job.error = f"No result within {MAX_POLL_SECONDS // 60} minutes"
                job.completed_at = datetime.now(timezone.utc)
                session.commit()
        finally:
            session.close()
    finally:
        with _poller_lock:
            _active_pollers.discard(job_id)


def _extract_error(raw: dict) -> str:
    error = raw.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    if error:
        return str(error)[:300]
    return str(raw.get("output", {}).get("message") or raw.get("message") or "")[:300]


def _finalize_result(session: Session, job: GenerationJob, adapter) -> None:
    result_info = adapter.fetch_result(job.provider_job_id)
    shot = session.get(Shot, job.shot_id)

    content: bytes
    if str(result_info.download_url).startswith("test-echo://"):
        # TEST adapter output — clearly labelled, never presented as a real video
        content = (b"TEST ADAPTER OUTPUT - NOT A REAL VIDEO\n" +
                   f"job={job.id} provider=test-echo generated={utcnow_iso()}\n".encode())
    else:
        content = adapter.download(result_info.download_url)

    checksum = hashlib.sha256(content).hexdigest()
    version = (session.scalar(select(func.max(GenerationResult.version_number)).where(
        GenerationResult.shot_id == job.shot_id)) or 0) + 1
    extension = ".mp4"
    folder = settings.repo_root / "renders" / "shots" / str(job.shot_id)
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"shot-{job.shot_id}-gen{job.attempt:02d}-v{version}{extension}"
    target = folder / filename
    target.write_bytes(content)

    result = GenerationResult(
        job_id=job.id, shot_id=job.shot_id, provider_key=job.provider_key,
        version_number=version,
        storage_mode="provider_result",
        repo_path=target.relative_to(settings.repo_root).as_posix(),
        uri=result_info.download_url, checksum=checksum,
        duration_seconds=(job.settings or {}).get("duration_seconds"),
        resolution=(job.settings or {}).get("resolution"),
        status="needs_review", file_size=len(content),
        provider_metadata={
            **_safe_raw(result_info.raw),
            "usage": result_info.usage,
            "test_adapter": job.provider_key == "test-echo",
        },
    )
    session.add(result)
    job.status = "needs_review"
    job.usage = result_info.usage or None
    job.completed_at = datetime.now(timezone.utc)
    job.poll_metadata = {**(job.poll_metadata or {}),
                         "result": {"download_url": result_info.download_url,
                                    "provider_raw": _safe_raw(result_info.raw)}}
    if shot is not None and shot.status == "ready_for_generation":
        shot.status = "generating"
        shot.generation_status = "generating"
    session.commit()


# ---------------------------------------------------------------------------
# Retry / cancel / review (PART 11, 16, 17)
# ---------------------------------------------------------------------------

def retry_job(db: Session, job_id: int, provider_key: str | None = None,
              settings_overrides: dict | None = None) -> GenerationJob:
    """Retry creates a NEW attempt — the failed job is preserved."""
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise ValueError("Job not found")
    if job.status not in ("failed", "cancelled", "rejected", "needs_review", "completed"):
        raise PermissionError(f"Cannot retry a job in status '{job.status}'")
    settings = {**(job.settings or {}), **(settings_overrides or {})}
    new_job = create_job(db, job.shot_id, provider_key or job.provider_key, settings)
    return new_job


def cancel_job(db: Session, job_id: int) -> GenerationJob:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise ValueError("Job not found")
    if job.status in ("completed", "needs_review", "approved"):
        raise PermissionError(f"Cannot cancel a job in status '{job.status}'")
    cancelled_upstream = False
    if job.provider_job_id:
        try:
            adapter = adapter_factory.get_video_adapter(job.provider_key)
            cancelled_upstream = adapter.cancel(job.provider_job_id)
        except (ProviderNotConfigured, ProviderApiError, ValueError):
            cancelled_upstream = False
    job.status = "cancelled"
    job.completed_at = datetime.now(timezone.utc)
    job.error = None if cancelled_upstream else (
        job.error or "Cancelled locally (provider cancellation not supported).")
    db.commit()
    db.refresh(job)
    return job


def review_result(db: Session, result_id: int, decision: str, reason: str | None = None) -> GenerationResult:
    result = db.get(GenerationResult, result_id)
    if result is None:
        raise ValueError("Result not found")
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be approved | rejected")
    if decision == "rejected" and not (reason or "").strip():
        raise PermissionError("A rejection reason is required")
    result.status = decision
    result.is_approved = decision == "approved"
    job = db.get(GenerationJob, result.job_id)
    if job is not None:
        job.status = decision
    shot = db.get(Shot, result.shot_id) if result.shot_id else None
    if shot is not None and decision == "approved":
        shot.generation_status = "generated"
        shot.status = "complete"           # shot has an approved generated version
    elif shot is not None and decision == "rejected":
        shot.generation_status = "pending" # ready to generate a new version
        if shot.status == "generating":
            shot.status = "needs_revision"
    from ..models import Approval
    db.add(Approval(
        entity_type="generation_result", entity_id=str(result_id), decision=decision,
        note=reason or f"result v{result.version_number} approved",
    ))
    db.commit()
    db.refresh(result)
    return result
