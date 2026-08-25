"""Phase 7 batch production: batch video/audio generation, Production
Assistant (QC-driven automation), queue priorities + worker concurrency,
retry policies. Approvals stay human; nothing publishes automatically."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AudioJob,
    AudioRecording,
    Character,
    Episode,
    GenerationResult,
    Scene,
    ScriptElement,
    Shot,
    TimelineItem,
    VoiceProfile,
)
from ..providers.registry import ProviderNotConfigured
from . import generation_service
from . import postproduction as pp

# retry classification (Step 12)
TEMPORARY_CODES = {"provider_api_error", "provider_timeout", "api_error"}
PERMANENT_CODES = {"invalid_request", "provider_not_configured", "missing_reference"}
USER_CODES = {"generation_failed", "user_rejection"}
AUTH_CODES = {"authentication_failed"}

DEFAULT_MAX_RETRIES = 3


def classify_failure(error_code: str | None) -> str:
    if error_code in TEMPORARY_CODES:
        return "temporary"        # safe to auto-retry
    if error_code in AUTH_CODES:
        return "auth"             # needs credential fix; manual retry
    if error_code in PERMANENT_CODES:
        return "permanent"        # retrying unchanged will not help
    return "unknown"


def retry_allowed(job_attempts: int, error_code: str | None, max_retries: int = DEFAULT_MAX_RETRIES) -> dict:
    kind = classify_failure(error_code)
    return {
        "classification": kind,
        "attempts": job_attempts,
        "max_retries": max_retries,
        "allowed": kind in ("temporary", "unknown") and job_attempts < max_retries,
        "reason": None if (kind in ("temporary", "unknown") and job_attempts < max_retries) else
                  f"{kind} failure — manual decision required" if kind != "temporary" else
                  f"max retries ({max_retries}) reached",
    }


# ==========================================================================
# Batch video (Steps 5, 7)
# ==========================================================================

def batch_targets(db: Session, episode_id: int | None = None, scene_id: int | None = None,
                  shot_ids: list[int] | None = None, mode: str = "missing") -> list[Shot]:
    """missing = no approved result; failed = last job failed; rejected = result
    rejected; new_versions = approved shots (explicit only)."""
    query = select(Shot).join(Scene, Shot.scene_id == Scene.id)
    if episode_id:
        query = query.where(Scene.episode_id == episode_id)
    if scene_id:
        query = query.where(Shot.scene_id == scene_id)
    if shot_ids:
        query = query.where(Shot.id.in_(shot_ids))
    shots = db.scalars(query.order_by(Scene.order_index, Shot.order_index)).all()
    targets = []
    for shot in shots:
        latest = db.scalar(select(GenerationResult).where(
            GenerationResult.shot_id == shot.id)
            .order_by(GenerationResult.version_number.desc()))
        if mode == "missing" and (latest is None or latest.status != "approved"):
            targets.append(shot)
        elif mode == "failed":
            from ..models import GenerationJob
            job = db.scalar(select(GenerationJob).where(
                GenerationJob.shot_id == shot.id).order_by(GenerationJob.id.desc()))
            if job is not None and job.status == "failed":
                targets.append(shot)
        elif mode == "rejected" and latest is not None and latest.status == "rejected":
            targets.append(shot)
        elif mode == "new_versions" and latest is not None and latest.status == "approved":
            targets.append(shot)  # explicit request only — never overwrites the approved version
    return targets


def queue_batch_video(db: Session, provider_key: str = "auto", settings: dict | None = None,
                      mode: str = "missing", auto_prepare: bool = False,
                      override_warnings: bool = False, **selectors) -> dict:
    """Queue generation for many shots.

    auto_prepare: promote draft shots that pass validation with no blocking
    errors (the technical gate) so mass production doesn't require 40 manual
    clicks. Warnings are only overridden when override_warnings=True is passed
    explicitly — otherwise those shots are skipped with reasons.
    """
    from ..models import Approval, ShotContinuity
    from ..services.shot_package import sync_continuity_records, validate_shot

    targets = batch_targets(db, mode=mode, **selectors)
    queued, skipped, prepared = [], [], []
    for shot in targets:
        try:
            if shot.status not in ("ready_for_generation", "generating", "generated",
                                   "needs_revision", "complete"):
                if not auto_prepare:
                    skipped.append({"shot": shot.shot_ref or shot.id,
                                    "reason": f"Shot status '{shot.status}' — approve it or pass auto_prepare=true"})
                    continue
                validation = validate_shot(db, shot)
                sync_continuity_records(db, shot, validation)
                errors = [f for f in validation["findings"]
                          if f["severity"] == "error" and not f["overridden"]]
                warnings_open = [f for f in validation["findings"]
                                 if f["severity"] == "warning" and not f["overridden"]]
                if errors:
                    skipped.append({"shot": shot.shot_ref or shot.id,
                                    "reason": f"{len(errors)} blocking error(s): " +
                                    "; ".join(f["key"] for f in errors[:3])})
                    continue
                if warnings_open and not override_warnings:
                    skipped.append({"shot": shot.shot_ref or shot.id,
                                    "reason": f"{len(warnings_open)} warning(s) — fix them or pass override_warnings=true"})
                    continue
                for finding in warnings_open:
                    db.add(ShotContinuity(
                        shot_id=shot.id, check_key=finding["key"],
                        severity="warning", message=finding["message"],
                        overridden=True,
                        override_explanation="Batch auto-prepare (user-requested override_warnings)."))
                    db.commit()
                    validation = validate_shot(db, shot)
                    sync_continuity_records(db, shot, validation)
                shot.status = "approved"
                db.add(Approval(entity_type="shot", entity_id=str(shot.id),
                                decision="approved", note="batch auto-prepare (validation passed)"))
                db.commit()
                shot.status = "ready_for_generation"
                db.add(Approval(entity_type="shot", entity_id=str(shot.id),
                                decision="approved", note="batch auto-prepare ready-for-generation"))
                db.commit()
                prepared.append(shot.shot_ref or shot.id)
            job = generation_service.create_job(db, shot.id, provider_key, dict(settings or {}))
            generation_service.submit_job(job.id)
            queued.append({"job_id": job.id, "shot": shot.shot_ref or shot.id})
        except (ProviderNotConfigured, PermissionError, ValueError) as error:
            skipped.append({"shot": shot.shot_ref or shot.id, "reason": str(error)[:160]})
    return {"queued": queued, "skipped": skipped, "prepared": prepared,
            "note": "Approved versions are never overwritten; retries create new attempts. "
                    "Creative approval of results always stays with you."}


# ==========================================================================
# Batch audio (Step 6)
# ==========================================================================

def batch_audio_report(db: Session, episode_id: int) -> dict:
    elements = db.scalars(select(ScriptElement).join(
        Scene, ScriptElement.scene_id == Scene.id)
        .where(Scene.episode_id == episode_id)).all()
    spoken = [e for e in elements if e.element_type in ("dialogue", "narration")]
    missing_lines, unapproved, approved = [], [], []
    characters_without_voices = set()
    for element in spoken:
        recording = pp._best_recording(db, element.id)
        if recording is None:
            missing_lines.append(element)
            if element.character_id:
                voice = db.scalar(select(VoiceProfile).where(
                    VoiceProfile.character_id == element.character_id))
                if voice is None:
                    character = db.get(Character, element.character_id)
                    characters_without_voices.add(character.name if character else str(element.character_id))
        elif recording.status == "approved":
            approved.append(element)
        else:
            unapproved.append(element)
    return {
        "total_spoken_lines": len(spoken),
        "approved": len(approved),
        "unapproved": len(unapproved),
        "missing": len(missing_lines),
        "characters_without_voice_profiles": sorted(characters_without_voices),
        "missing_line_ids": [e.id for e in missing_lines],
    }


def queue_batch_audio(db: Session, episode_id: int, include_approved: bool = False,
                      provider_key: str = "auto") -> dict:
    report = batch_audio_report(db, episode_id)
    queued, skipped = [], []
    element_ids = list(report["missing_line_ids"])
    if include_approved:
        elements = db.scalars(select(ScriptElement).join(
            Scene, ScriptElement.scene_id == Scene.id)
            .where(Scene.episode_id == episode_id)).all()
        element_ids = [e.id for e in elements if e.element_type in ("dialogue", "narration")]
    for element_id in element_ids:
        element = db.get(ScriptElement, element_id)
        if element is None:
            continue
        voice = db.scalar(select(VoiceProfile).where(
            VoiceProfile.character_id == element.character_id)) if element.character_id else None
        try:
            recording = pp.create_recording_from_element(db, element, voice.id if voice else None)
            pp.start_audio_generation(db, recording.id, provider_key)
            queued.append({"recording_id": recording.id, "text": (element.text or "")[:40]})
        except (ProviderNotConfigured, ValueError) as error:
            skipped.append({"text": (element.text or "")[:40], "reason": str(error)[:160]})
    return {"queued": queued, "skipped": skipped, "report": report,
            "note": "Already-approved audio is never regenerated unless explicitly requested."}


# ==========================================================================
# Production Assistant (Step 8)
# ==========================================================================

def production_assistant(db: Session, episode_id: int) -> dict:
    episode = db.get(Episode, episode_id)
    if episode is None:
        raise ValueError("Episode not found")
    scenes = db.scalars(select(Scene).where(Scene.episode_id == episode_id)
                        .order_by(Scene.order_index)).all()
    shots = db.scalars(select(Shot).join(Scene, Shot.scene_id == Scene.id)
                       .where(Scene.episode_id == episode_id)
                       .order_by(Scene.order_index, Shot.order_index)).all()
    ready_shots, missing_shots, blocked_shots = [], [], []
    for shot in shots:
        result = db.scalar(select(GenerationResult).where(
            GenerationResult.shot_id == shot.id)
            .order_by(GenerationResult.version_number.desc()))
        ref = shot.shot_ref or f"Shot {shot.number}"
        if result is not None and result.status == "approved":
            ready_shots.append(ref)
        elif result is None:
            from ..services.shot_package import validate_shot
            validation = validate_shot(db, shot)
            (blocked_shots if any(f["severity"] == "error" for f in validation["findings"])
             else missing_shots).append(ref)
        else:
            missing_shots.append(f"{ref} (v{result.version_number} {result.status})")
    audio = batch_audio_report(db, episode_id)
    qc = pp.qc_check(db, episode_id)

    auto_generatable = []
    for ref in missing_shots:
        auto_generatable.append({"item": ref, "action": "queue video generation", "needs": "generation"})
    for line_id in audio["missing_line_ids"]:
        element = db.get(ScriptElement, line_id)
        auto_generatable.append({"item": (element.text or "")[:50] if element else str(line_id),
                                 "action": "queue audio generation", "needs": "generation"})
    return {
        "episode_id": episode_id,
        "summary": {
            "shots_total": len(shots),
            "shots_approved": len(ready_shots),
            "audio_total": audio["total_spoken_lines"],
            "audio_approved": audio["approved"],
            "qc_status": qc["status"],
            "qc_blocking": qc["blocked"],
        },
        "ready": {"shots": ready_shots, "audio_approved_count": audio["approved"]},
        "missing": {"shots": missing_shots, "audio_missing_count": audio["missing"],
                    "audio_unapproved_count": audio["unapproved"]},
        "blocked": {"shots_needing_fixes": blocked_shots,
                    "qc_findings": [f"{f['key']}: {f['message']}" for f in qc["findings"] if f["severity"] == "blocked"],
                    "characters_without_voices": audio["characters_without_voice_profiles"]},
        "can_generate_automatically": auto_generatable,
        "requires_human_approval": [
            "Approving generated video results",
            "Approving audio recordings",
            "Approving exports and shorts",
            "Overriding QC findings for render",
        ],
        "note": "The assistant queues generation only. Creative approval always stays with you.",
    }
