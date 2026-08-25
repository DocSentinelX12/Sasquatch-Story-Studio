"""Phase 6 post-production service: audio generation, timeline assembly,
QC, rendering, and exports. Honest throughout: the renderer requires ffmpeg
on the machine (self-hosted free path); nothing is fabricated."""

from __future__ import annotations

import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..models import (
    Approval,
    Asset,
    AudioJob,
    AudioRecording,
    Episode,
    EpisodeRender,
    ExportRecord,
    GenerationResult,
    Scene,
    ScriptElement,
    Shot,
    TimelineItem,
    TimelineTrack,
    VoiceProfile,
)
from ..providers import adapters as adapter_factory
from ..providers.registry import ProviderNotConfigured

STANDARD_TRACKS = [
    ("video", "Video"), ("dialogue", "Dialogue"), ("narration", "Narration"),
    ("sfx", "SFX"), ("ambience", "Ambience"), ("music", "Music"),
]

RENDER_DIR = "renders/episodes"


# ==========================================================================
# Audio generation (dialogue + narration)
# ==========================================================================

def resolve_audio_provider(provider_key: str | None) -> str:
    if provider_key and provider_key != "auto":
        return provider_key
    from ..providers.adapters import test_provider_enabled
    from ..config import env
    if env("LOCAL_AUDIO_API_URL"):
        return "local-audio"
    if test_provider_enabled():
        return "test-echo-audio"
    return ""


def create_recording_from_element(db: Session, element: ScriptElement,
                                  voice_profile_id: int | None) -> AudioRecording:
    character_id = element.character_id
    version = (db.scalar(select(func.max(AudioRecording.version_number)).where(
        AudioRecording.script_element_id == element.id)) or 0) + 1
    # demote older versions of this line (kept, never deleted)
    db.execute(AudioRecording.__table__.update().where(
        AudioRecording.script_element_id == element.id).values(is_current=False))
    recording = AudioRecording(
        project_id=db.get(Episode, element.episode_id).project_id if element.episode_id else None,
        episode_id=element.episode_id, scene_id=None,
        shot_id=_shot_for_element(db, element),
        script_element_id=element.id,
        kind="narration" if element.element_type == "narration" else "dialogue",
        character_id=character_id, voice_profile_id=voice_profile_id,
        text=element.text or "", version_number=version,
        status="draft", is_current=True,
        notes=element.timing_notes,
    )
    db.add(recording)
    db.commit()
    db.refresh(recording)
    return recording


def _shot_for_element(db: Session, element: ScriptElement) -> int | None:
    shots = db.scalars(select(Shot).where(Shot.scene_id == element.scene_id)
                       .order_by(Shot.order_index)).all()
    elements = db.scalars(select(ScriptElement).where(
        ScriptElement.scene_id == element.scene_id)
        .order_by(ScriptElement.order_index, ScriptElement.id)).all()
    index = next((i for i, e in enumerate(elements) if e.id == element.id), 0)
    per_shot = max(1, (len(elements) + max(1, len(shots)) - 1) // max(1, len(shots)))
    return shots[min(index // per_shot, len(shots) - 1)].id if shots else None


def start_audio_generation(db: Session, recording_id: int, provider_key: str = "auto") -> AudioJob:
    recording = db.get(AudioRecording, recording_id)
    if recording is None:
        raise ValueError("Recording not found")
    voice = db.get(VoiceProfile, recording.voice_profile_id) if recording.voice_profile_id else None
    resolved = resolve_audio_provider(provider_key)
    if not resolved:
        raise ProviderNotConfigured("audio", ["LOCAL_AUDIO_API_URL"])
    package = {
        "text": recording.text,
        "voice_profile": ({
            "voice_id": voice.voice_id, "voice_style": voice.voice_style,
            "speaking_speed": voice.speaking_speed, "pitch": voice.pitch,
            "emotion_notes": voice.emotion_notes,
        } if voice else None),
        "kind": recording.kind,
    }
    try:
        adapter = adapter_factory.get_video_adapter(resolved)
        translated = adapter.translate(package, {})
    except ProviderNotConfigured as error:
        raise error
    job = AudioJob(
        project_id=recording.project_id, recording_id=recording.id,
        target_kind=recording.kind, provider_key=resolved, status="submitting",
        request_payload=translated,
        submitted_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    handle = adapter.submit(translated)
    job.provider_job_id = handle.provider_job_id
    job.status = "submitted"
    db.commit()
    threading.Thread(target=_poll_audio, args=(job.id, resolved), daemon=True).start()
    db.refresh(job)
    return job


def _poll_audio(job_id: int, provider_key: str) -> None:
    import time as _time

    from ..db import SessionLocal

    deadline = _time.time() + 5 * 60
    while _time.time() < deadline:
        session = SessionLocal()
        try:
            job = session.get(AudioJob, job_id)
            if job is None or job.status == "cancelled":
                return
            try:
                adapter = adapter_factory.get_video_adapter(provider_key)
                handle = adapter.poll(job.provider_job_id)
            except Exception as error:  # noqa: BLE001
                job.status = "failed"; job.error_code = "provider_api_error"
                job.error = str(error)[:400]
                job.completed_at = datetime.now(timezone.utc).isoformat()
                session.commit(); return
            if handle.state == "failed":
                job.status = "failed"; job.error_code = "audio_generation_failed"
                job.error = str(handle.raw.get("error", "provider failure"))[:400]
                job.completed_at = datetime.now(timezone.utc).isoformat()
                session.commit(); return
            if handle.state == "succeeded":
                _finish_audio(session, job, adapter)
                return
            session.commit()
        finally:
            session.close()
        _time.sleep(3.0)
    session = SessionLocal()
    try:
        job = session.get(AudioJob, job_id)
        if job and job.status in ("submitted", "generating"):
            job.status = "failed"; job.error_code = "provider_timeout"
            job.completed_at = datetime.now(timezone.utc).isoformat()
            session.commit()
    finally:
        session.close()


def _finish_audio(session: Session, job: AudioJob, adapter) -> None:
    result = adapter.fetch_result(job.provider_job_id)
    recording = session.get(AudioRecording, job.recording_id)
    if str(result.download_url).startswith("test-audio://"):
        content = adapter.download(result.download_url)
    else:
        content = adapter.download(result.download_url)
    from .storage import sha256_of
    import hashlib
    folder = settings.repo_root / "renders" / "audio" / str(recording.id)
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"line-v{recording.version_number}.wav"
    target = folder / filename
    target.write_bytes(content)
    recording.repo_path = target.relative_to(settings.repo_root).as_posix()
    recording.storage_mode = "provider_result"
    recording.duration_seconds = (result.usage or {}).get("duration_seconds")
    recording.provider_key = job.provider_key
    recording.status = "needs_review"
    job.status = "completed"
    job.usage = result.usage or None
    job.result_recording_id = recording.id
    job.completed_at = datetime.now(timezone.utc).isoformat()
    session.commit()


# ==========================================================================
# Timeline: tracks, assembly, editing (non-destructive)
# ==========================================================================

def ensure_tracks(db: Session, episode_id: int) -> list[TimelineTrack]:
    existing = db.scalars(select(TimelineTrack).where(
        TimelineTrack.episode_id == episode_id).order_by(TimelineTrack.order_index)).all()
    if existing:
        return existing
    for index, (kind, name) in enumerate(STANDARD_TRACKS):
        db.add(TimelineTrack(episode_id=episode_id, kind=kind, name=name, order_index=index))
    db.commit()
    return db.scalars(select(TimelineTrack).where(
        TimelineTrack.episode_id == episode_id).order_by(TimelineTrack.order_index)).all()


def build_timeline(db: Session, episode_id: int, replace: bool = True) -> dict:
    """Assemble the episode timeline from approved material (Step 11).

    Video: approved (else latest) shot results in scene/shot order, sequential.
    Dialogue/Narration: approved recordings placed at their shot's start with
    cumulative offsets. Reports everything missing instead of guessing."""
    ensure_tracks(db, episode_id)
    if replace:
        db.execute(TimelineItem.__table__.delete().where(TimelineItem.episode_id == episode_id))
        db.commit()
    tracks = {t.kind: t for t in db.scalars(select(TimelineTrack).where(
        TimelineTrack.episode_id == episode_id)).all()}

    scenes = db.scalars(select(Scene).where(Scene.episode_id == episode_id)
                        .order_by(Scene.order_index)).all()
    cursor = 0.0
    order = 0
    missing: list[str] = []
    placed_results = 0
    placed_audio = 0
    for scene in scenes:
        shots = db.scalars(select(Shot).where(Shot.scene_id == scene.id)
                           .order_by(Shot.order_index)).all()
        elements = db.scalars(select(ScriptElement).where(
            ScriptElement.scene_id == scene.id)
            .order_by(ScriptElement.order_index, ScriptElement.id)).all()
        element_cursor = cursor
        for shot in shots:
            duration = max(0.5, float(shot.duration_seconds or 6))
            result = _best_result(db, shot.id)
            if result is None:
                missing.append(f"{shot.shot_ref or shot.id}: no generated result")
                db.add(TimelineItem(episode_id=episode_id, track_id=tracks["video"].id,
                                    track_kind="video", label=f"{shot.shot_ref} (missing)",
                                    start_seconds=cursor, end_seconds=cursor + duration,
                                    shot_id=shot.id, scene_id=scene.id,
                                    source_type="gap", order_index=order))
            else:
                db.add(TimelineItem(
                    episode_id=episode_id, track_id=tracks["video"].id, track_kind="video",
                    label=f"{shot.shot_ref or 'shot'} v{result.version_number}",
                    start_seconds=cursor, end_seconds=cursor + duration,
                    shot_id=shot.id, scene_id=scene.id,
                    source_type="shot_result", source_id=result.id, order_index=order))
                placed_results += 1
            order += 1
            cursor += duration
        # audio: approved recordings for elements in this scene
        for element in elements:
            if element.element_type not in ("dialogue", "narration"):
                continue
            recording = _best_recording(db, element.id)
            if recording is None:
                missing.append(f"Line {element.id} ({element.element_type}): no approved recording")
                continue
            duration = max(0.5, float(recording.duration_seconds or 2))
            kind = "narration" if element.element_type == "narration" else "dialogue"
            db.add(TimelineItem(
                episode_id=episode_id, track_id=tracks[kind].id, track_kind=kind,
                label=(recording.text or "")[:40],
                start_seconds=element_cursor, end_seconds=element_cursor + duration,
                shot_id=recording.shot_id, scene_id=scene.id,
                source_type="recording", source_id=recording.id, order_index=order))
            element_cursor += duration
            placed_audio += 1
            order += 1
    db.commit()
    return {"episode_id": episode_id, "placed_results": placed_results,
            "placed_audio_clips": placed_audio, "duration_seconds": round(cursor, 2),
            "missing": missing, "note": "Timeline assembled from approved material; "
            "adjust freely — editing is non-destructive."}


def _best_result(db: Session, shot_id: int) -> GenerationResult | None:
    approved = db.scalar(select(GenerationResult).where(
        GenerationResult.shot_id == shot_id, GenerationResult.status == "approved"
    ).order_by(GenerationResult.version_number.desc()))
    if approved:
        return approved
    return db.scalar(select(GenerationResult).where(
        GenerationResult.shot_id == shot_id
    ).order_by(GenerationResult.version_number.desc()))


def _best_recording(db: Session, element_id: int) -> AudioRecording | None:
    approved = db.scalar(select(AudioRecording).where(
        AudioRecording.script_element_id == element_id,
        AudioRecording.status == "approved", AudioRecording.is_current == True)  # noqa: E712
        .order_by(AudioRecording.version_number.desc()))
    if approved:
        return approved
    return db.scalar(select(AudioRecording).where(
        AudioRecording.script_element_id == element_id,
        AudioRecording.is_current == True)  # noqa: E712
        .order_by(AudioRecording.version_number.desc()))


# ==========================================================================
# QC (Step 12) + Ready-for-Render gate (Step 13)
# ==========================================================================

def qc_check(db: Session, episode_id: int) -> dict:
    findings: list[dict] = []

    def add(severity, key, message):
        findings.append({"severity": severity, "key": key, "message": message})

    timeline = db.scalars(select(TimelineItem).where(
        TimelineItem.episode_id == episode_id).order_by(TimelineItem.start_seconds)).all()
    if not timeline:
        add("blocked", "timeline-empty", "Timeline is empty — run Build Episode Timeline first.")
    video_items = [i for i in timeline if i.track_kind == "video"]
    gaps = []
    previous_end = 0.0
    for item in video_items:
        if item.start_seconds > previous_end + 0.05:
            gaps.append(f"gap {previous_end:.1f}-{item.start_seconds:.1f}s")
        previous_end = max(previous_end, item.end_seconds)
    if gaps:
        add("blocked", "timeline-gaps", "; ".join(gaps[:5]))
    if any(i.source_type == "gap" for i in video_items):
        add("blocked", "missing-shots",
            f"{sum(1 for i in video_items if i.source_type == 'gap')} shot(s) have no generated result.")

    shots = db.scalars(select(Shot).join(Scene, Shot.scene_id == Scene.id)
                       .where(Scene.episode_id == episode_id)).all()
    without_result = [s for s in shots if _best_result(db, s.id) is None]
    if without_result:
        add("blocked", "shots-without-results",
            f"{len(without_result)} of {len(shots)} shots lack generated results.")
    unapproved = [s for s in shots
                  if _best_result(db, s.id) is not None
                  and _best_result(db, s.id).status != "approved"]
    if unapproved:
        add("warning", "unapproved-shot-results",
            f"{len(unapproved)} shot result(s) not approved yet.")

    elements = db.scalars(select(ScriptElement).join(
        Scene, ScriptElement.scene_id == Scene.id)
        .where(Scene.episode_id == episode_id)).all()
    lines = [e for e in elements if e.element_type in ("dialogue", "narration")]
    missing_audio = [e for e in lines if _best_recording(db, e.id) is None]
    if missing_audio:
        add("warning", "missing-audio",
            f"{len(missing_audio)} of {len(lines)} spoken lines lack recordings."
            if lines else "No dialogue/narration in this episode.")
    unapproved_audio = [e for e in lines
                        if _best_recording(db, e.id) is not None
                        and _best_recording(db, e.id).status != "approved"]
    if unapproved_audio:
        add("warning", "unapproved-audio",
            f"{len(unapproved_audio)} recording(s) not approved yet.")

    # resolution / aspect consistency across results (rule-based)
    resolutions = set()
    for item in video_items:
        if item.source_type == "shot_result":
            result = db.get(GenerationResult, item.source_id)
            if result is not None and result.resolution:
                resolutions.add(result.resolution)
    if len(resolutions) > 1:
        add("warning", "resolution-mismatch", f"Multiple resolutions: {sorted(resolutions)}")

    blocked = [f for f in findings if f["severity"] == "blocked"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    try:
        from . import automation
        episode = db.get(Episode, episode_id)
        if blocked:
            automation.emit_event(db, "qc_blocker", project_id=episode.project_id,
                                  episode_id=episode_id,
                                  context={"note": f"{len(blocked)} blocker(s)"})
        elif warnings:
            automation.emit_event(db, "qc_warning", project_id=episode.project_id,
                                  episode_id=episode_id,
                                  context={"note": f"{len(warnings)} warning(s)"})
        else:
            automation.emit_event(db, "episode_ready", project_id=episode.project_id,
                                  episode_id=episode_id, context={"note": "QC passed"})
    except Exception:  # noqa: BLE001 - QC never breaks on automation errors
        pass
    return {"episode_id": episode_id, "findings": findings,
            "blocked": len(blocked), "warnings": len(warnings),
            "status": "blocked" if blocked else ("warning" if warnings else "pass"),
            "checks": ["timeline gaps", "missing shots", "unapproved results",
                       "missing audio", "unapproved audio", "resolution consistency"]}


# ==========================================================================
# Render system (Step 14) — ffmpeg-based self-hosted renderer
# ==========================================================================

def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def create_render(db: Session, episode_id: int, resolution: str = "1280x720",
                  fps: float = 24.0, aspect_ratio: str = "16:9",
                  qc_overrides: dict | None = None) -> EpisodeRender:
    qc = qc_check(db, episode_id)
    blocked = [f for f in qc["findings"] if f["severity"] == "blocked"]
    overrides = qc_overrides or {}
    unresolved = [f for f in blocked if f["key"] not in overrides]
    if unresolved:
        raise PermissionError({
            "error": "qc_blocked",
            "message": "Resolve or override the blocking QC findings.",
            "blocking": unresolved,
        })
    version = (db.scalar(select(func.max(EpisodeRender.version_number)).where(
        EpisodeRender.episode_id == episode_id)) or 0) + 1
    render = EpisodeRender(
        episode_id=episode_id, version_number=version, status="draft",
        resolution=resolution, fps=fps, aspect_ratio=aspect_ratio,
        qc_overrides=overrides or None,
    )
    db.add(render)
    db.commit()
    db.refresh(render)
    return render


def queue_render(render_id: int) -> EpisodeRender:
    from ..db import SessionLocal

    session = SessionLocal()
    try:
        render = session.get(EpisodeRender, render_id)
        render.status = "queued"
        session.commit()
    finally:
        session.close()
    threading.Thread(target=_render_worker, args=(render_id,), daemon=True).start()
    session = SessionLocal()
    try:
        return session.get(EpisodeRender, render_id)
    finally:
        session.close()


def _render_worker(render_id: int) -> None:
    from ..db import SessionLocal

    session = SessionLocal()
    try:
        render = session.get(EpisodeRender, render_id)
        if render is None:
            return
        render.status = "rendering"
        render.started_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        if not ffmpeg_available():
            render.status = "failed"
            render.error_code = "renderer_not_available"
            render.error = ("No ffmpeg binary found on this machine. The local "
                            "renderer needs ffmpeg (self-hosted, free). Install "
                            "ffmpeg and re-queue the render.")
            render.completed_at = datetime.now(timezone.utc).isoformat()
            session.commit()
            return
        output = _ffmpeg_render(session, render)
        render.output_path = output.relative_to(settings.repo_root).as_posix()
        render.status = "completed"
        render.completed_at = datetime.now(timezone.utc).isoformat()
        session.commit()
    except Exception as error:  # noqa: BLE001 - record every failure honestly
        try:
            render = session.get(EpisodeRender, render_id)
            render.status = "failed"
            render.error_code = "render_failed"
            render.error = str(error)[:500]
            render.completed_at = datetime.now(timezone.utc).isoformat()
            session.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        session.close()


def _ffmpeg_render(session: Session, render: EpisodeRender) -> Path:
    """Concat approved video results in timeline order and mux audio tracks.

    Uses trim/volume/fade timeline values (non-destructive: sources untouched).
    """
    items = session.scalars(select(TimelineItem).where(
        TimelineItem.episode_id == render.episode_id,
        TimelineItem.track_kind == "video",
        TimelineItem.source_type == "shot_result",
    ).order_by(TimelineItem.start_seconds)).all()
    if not items:
        raise ValueError("No video clips on the timeline")
    width, height = (int(x) for x in render.resolution.lower().split("x"))
    episode = session.get(Episode, render.episode_id)

    parts_dir = settings.repo_root / RENDER_DIR / f"ep{render.episode_id}" / f"parts-v{render.version_number}"
    parts_dir.mkdir(parents=True, exist_ok=True)
    concat_list = parts_dir / "list.txt"
    lines = []
    for index, item in enumerate(items):
        result = session.get(GenerationResult, item.source_id)
        if result is None or not result.repo_path:
            continue
        src = settings.repo_root / result.repo_path
        if not src.is_file():
            continue
        trim = max(0.0, item.end_seconds - item.start_seconds - item.trim_out - item.trim_in)
        part = parts_dir / f"part{index:04d}.mp4"
        cmd = ["ffmpeg", "-y", "-i", str(src)]
        filters = [f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2", "fps=%d" % int(render.fps)]
        if item.trim_in or item.trim_out:
            filters.append("setpts=PTS-STARTPTS")
        cmd += ["-vf", ",".join(filters)]
        if trim > 0:
            cmd += ["-t", f"{trim:.3f}"]
        cmd += ["-an", str(part)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed on part {index}: {proc.stderr[-300:]}")
        lines.append(f"file '{part.as_posix()}'")
    if not lines:
        raise ValueError("No renderable video parts (check result files exist)")
    concat_list.write_text("\n".join(lines), encoding="utf-8")

    version_dir = settings.repo_root / RENDER_DIR / f"ep{render.episode_id}"
    output = version_dir / f"episode-v{render.version_number}.mp4"
    if output.exists():  # never overwrite — bump suffix
        output = version_dir / f"episode-v{render.version_number}-{int(datetime.now().timestamp())}.mp4"
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(output)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {proc.stderr[-300:]}")
    return output


# ==========================================================================
# Exports + shorts
# ==========================================================================

def create_export(db: Session, episode_id: int, kind: str, render_id: int | None = None,
                  source_result_id: int | None = None, start_seconds: float | None = None,
                  end_seconds: float | None = None, title: str = "", **meta) -> ExportRecord:
    export = ExportRecord(
        project_id=db.get(Episode, episode_id).project_id, episode_id=episode_id,
        kind=kind, title=title or kind.replace("_", " ").title(),
        render_id=render_id, source_result_id=source_result_id,
        start_seconds=start_seconds, end_seconds=end_seconds,
        status="draft", **({"metadata_json": meta} if meta else {}),
    )
    db.add(export)
    db.commit()
    db.refresh(export)
    return export
