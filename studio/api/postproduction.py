"""Phase 6 API: voices, recordings, timeline, QC, renders, exports."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..models import (AudioJob, AudioRecording, Episode, EpisodeRender, ExportRecord,
                      ScriptElement, TimelineItem, TimelineTrack, VoiceProfile)
from ..providers.registry import ProviderNotConfigured
from ..services import postproduction as pp
from ..services.storage import resolve_repo_path
from .deps import get_db, row_to_dict

router = APIRouter(prefix="/api", tags=["postproduction"])


# ---------- voices ----------
class VoiceCreate(BaseModel):
    project_id: int
    character_id: Optional[int] = None
    name: str
    role: str = "character"
    provider_key: Optional[str] = None
    voice_id: Optional[str] = None
    voice_style: Optional[str] = None
    speaking_speed: float = 1.0
    pitch: Optional[float] = None
    emotion_notes: Optional[str] = None


@router.get("/voices")
def list_voices(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = select(VoiceProfile)
    if project_id:
        query = query.where(VoiceProfile.project_id == project_id)
    return {"voices": [row_to_dict(v) for v in db.scalars(query).all()]}


@router.post("/voices", status_code=201)
def create_voice(payload: VoiceCreate, db: Session = Depends(get_db)):
    voice = VoiceProfile(**payload.model_dump())
    db.add(voice); db.commit(); db.refresh(voice)
    return row_to_dict(voice)


@router.patch("/voices/{voice_id}")
def update_voice(voice_id: int, payload: dict, db: Session = Depends(get_db)):
    voice = db.get(VoiceProfile, voice_id)
    if voice is None:
        raise HTTPException(404, "Voice not found")
    for key, value in payload.items():
        if key in VoiceProfile.__table__.columns.keys() and key != "id":
            setattr(voice, key, value)
    db.commit(); db.refresh(voice)
    return row_to_dict(voice)


# ---------- recordings (dialogue + narration) ----------
@router.get("/audio/recordings")
def list_recordings(episode_id: Optional[int] = None, kind: Optional[str] = None,
                    db: Session = Depends(get_db)):
    query = select(AudioRecording)
    if episode_id:
        query = query.where(AudioRecording.episode_id == episode_id)
    if kind:
        query = query.where(AudioRecording.kind == kind)
    recordings = db.scalars(query.order_by(AudioRecording.id.desc())).all()
    return {"recordings": [row_to_dict(r) for r in recordings]}


@router.post("/audio/recordings/from-script/{element_id}", status_code=201)
def create_recording(element_id: int, voice_profile_id: Optional[int] = None,
                     db: Session = Depends(get_db)):
    element = db.get(ScriptElement, element_id)
    if element is None:
        raise HTTPException(404, "Script element not found")
    if element.element_type not in ("dialogue", "narration"):
        raise HTTPException(422, "Only dialogue/narration elements can be recorded")
    recording = pp.create_recording_from_element(db, element, voice_profile_id)
    return row_to_dict(recording)


@router.post("/audio/recordings/{recording_id}/generate")
def generate_recording(recording_id: int, provider_key: str = "auto",
                       db: Session = Depends(get_db)):
    try:
        job = pp.start_audio_generation(db, recording_id, provider_key)
    except ProviderNotConfigured as error:
        raise HTTPException(409, {"error": "provider_not_configured",
                                  "message": str(error)}) from error
    return row_to_dict(job)


@router.get("/audio/jobs")
def audio_jobs(recording_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = select(AudioJob)
    if recording_id:
        query = query.where(AudioJob.recording_id == recording_id)
    return {"jobs": [row_to_dict(j) for j in db.scalars(query.order_by(AudioJob.id.desc()).limit(100)).all()]}


@router.post("/audio/recordings/{recording_id}/review")
def review_recording(recording_id: int, decision: str, reason: Optional[str] = None,
                     db: Session = Depends(get_db)):
    recording = db.get(AudioRecording, recording_id)
    if recording is None:
        raise HTTPException(404, "Recording not found")
    if decision not in ("approved", "rejected"):
        raise HTTPException(422, "decision must be approved|rejected")
    if decision == "rejected" and not (reason or "").strip():
        raise HTTPException(422, "Rejection reason required")
    recording.status = decision
    from ..models import Approval
    db.add(Approval(entity_type="audio_recording", entity_id=str(recording_id),
                    decision=decision, note=reason))
    db.commit(); db.refresh(recording)
    return row_to_dict(recording)


@router.get("/audio/recordings/{recording_id}/file")
def recording_file(recording_id: int, db: Session = Depends(get_db)):
    recording = db.get(AudioRecording, recording_id)
    if recording is None or not recording.repo_path:
        raise HTTPException(404, "Audio not available")
    path = resolve_repo_path(recording.repo_path)
    if path is None:
        raise HTTPException(404, "File missing")
    return FileResponse(path, media_type="audio/wav")


# ---------- timeline ----------
@router.get("/episodes/{episode_id}/timeline")
def get_timeline(episode_id: int, db: Session = Depends(get_db)):
    pp.ensure_tracks(db, episode_id)
    tracks = db.scalars(select(TimelineTrack).where(
        TimelineTrack.episode_id == episode_id).order_by(TimelineTrack.order_index)).all()
    items = db.scalars(select(TimelineItem).where(
        TimelineItem.episode_id == episode_id).order_by(TimelineItem.start_seconds)).all()
    duration = max((i.end_seconds for i in items), default=0.0)
    return {"tracks": [row_to_dict(t) for t in tracks],
            "items": [row_to_dict(i) for i in items],
            "duration_seconds": round(duration, 2)}


@router.post("/episodes/{episode_id}/timeline/build")
def build_timeline(episode_id: int, db: Session = Depends(get_db)):
    return pp.build_timeline(db, episode_id)


class TrackUpdate(BaseModel):
    volume: Optional[float] = None
    muted: Optional[bool] = None
    solo: Optional[bool] = None


@router.patch("/timeline/tracks/{track_id}")
def update_track(track_id: int, payload: TrackUpdate, db: Session = Depends(get_db)):
    track = db.get(TimelineTrack, track_id)
    if track is None:
        raise HTTPException(404, "Track not found")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(track, key, value)
    db.commit(); db.refresh(track)
    return row_to_dict(track)


class ItemUpdate(BaseModel):
    start_seconds: Optional[float] = None
    end_seconds: Optional[float] = None
    trim_in: Optional[float] = None
    trim_out: Optional[float] = None
    volume_gain: Optional[float] = None
    fade_in: Optional[float] = None
    fade_out: Optional[float] = None
    locked: Optional[bool] = None


@router.patch("/timeline/items/{item_id}")
def update_item(item_id: int, payload: ItemUpdate, db: Session = Depends(get_db)):
    item = db.get(TimelineItem, item_id)
    if item is None:
        raise HTTPException(404, "Clip not found")
    if item.locked:
        raise HTTPException(409, "Clip is locked")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(item, key, value)
    db.commit(); db.refresh(item)
    return row_to_dict(item)


@router.post("/timeline/items/{item_id}/split")
def split_item(item_id: int, at_seconds: float, db: Session = Depends(get_db)):
    item = db.get(TimelineItem, item_id)
    if item is None:
        raise HTTPException(404, "Clip not found")
    if not (item.start_seconds < at_seconds < item.end_seconds):
        raise HTTPException(422, "Split point must be inside the clip")
    clone = TimelineItem(
        episode_id=item.episode_id, track_id=item.track_id, track_kind=item.track_kind,
        label=item.label, start_seconds=at_seconds, end_seconds=item.end_seconds,
        shot_id=item.shot_id, scene_id=item.scene_id, asset_id=item.asset_id,
        source_type=item.source_type, source_id=item.source_id,
        trim_in=item.trim_in + (at_seconds - item.start_seconds),
        order_index=item.order_index + 1,
        volume_gain=item.volume_gain, fade_in=0.0, fade_out=item.fade_out,
    )
    item.end_seconds = at_seconds
    item.fade_out = 0.0
    db.add(clone); db.commit(); db.refresh(clone)
    return row_to_dict(clone)


@router.post("/timeline/items/{item_id}/duplicate", status_code=201)
def duplicate_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(TimelineItem, item_id)
    if item is None:
        raise HTTPException(404, "Clip not found")
    length = item.end_seconds - item.start_seconds
    clone = TimelineItem(
        episode_id=item.episode_id, track_id=item.track_id, track_kind=item.track_kind,
        label=item.label, start_seconds=item.end_seconds, end_seconds=item.end_seconds + length,
        shot_id=item.shot_id, scene_id=item.scene_id, asset_id=item.asset_id,
        source_type=item.source_type, source_id=item.source_id,
        trim_in=item.trim_in, trim_out=item.trim_out, order_index=item.order_index + 1,
        volume_gain=item.volume_gain, fade_in=item.fade_in, fade_out=item.fade_out,
    )
    db.add(clone); db.commit(); db.refresh(clone)
    return row_to_dict(clone)


@router.delete("/timeline/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(TimelineItem, item_id)
    if item is None:
        raise HTTPException(404, "Clip not found")
    db.delete(item); db.commit()
    return None  # source assets are never deleted


# ---------- QC + renders ----------
@router.get("/episodes/{episode_id}/qc")
def episode_qc(episode_id: int, db: Session = Depends(get_db)):
    return pp.qc_check(db, episode_id)


class RenderCreate(BaseModel):
    resolution: str = "1280x720"
    fps: float = 24.0
    aspect_ratio: str = "16:9"
    qc_overrides: Optional[dict] = None


@router.post("/episodes/{episode_id}/renders", status_code=201)
def create_render(episode_id: int, payload: RenderCreate, db: Session = Depends(get_db)):
    try:
        render = pp.create_render(db, episode_id, payload.resolution, payload.fps,
                                  payload.aspect_ratio, payload.qc_overrides)
    except PermissionError as error:
        detail = error.args[0] if error.args else str(error)
        raise HTTPException(409, detail) from error
    return row_to_dict(render)


@router.get("/episodes/{episode_id}/renders")
def list_renders(episode_id: int, db: Session = Depends(get_db)):
    renders = db.scalars(select(EpisodeRender).where(
        EpisodeRender.episode_id == episode_id).order_by(EpisodeRender.version_number)).all()
    return {"renders": [row_to_dict(r) for r in renders], "ffmpeg_available": pp.ffmpeg_available()}


@router.post("/renders/{render_id}/queue")
def queue_render(render_id: int, db: Session = Depends(get_db)):
    render = db.get(EpisodeRender, render_id)
    if render is None:
        raise HTTPException(404, "Render not found")
    if render.status not in ("draft", "failed"):
        raise HTTPException(409, f"Cannot queue a render in status '{render.status}'")
    result = pp.queue_render(render_id)
    return row_to_dict(result)


@router.get("/renders/{render_id}/file")
def render_file(render_id: int, db: Session = Depends(get_db)):
    render = db.get(EpisodeRender, render_id)
    if render is None or not render.output_path:
        raise HTTPException(404, "Render output not available")
    path = resolve_repo_path(render.output_path)
    if path is None:
        raise HTTPException(404, "Render file missing")
    return FileResponse(path, media_type="video/mp4")


# ---------- exports + shorts ----------
class ExportCreate(BaseModel):
    kind: str = Field(pattern="^(full_episode|trailer|short_vertical|clip_horizontal|clip_vertical)$")
    render_id: Optional[int] = None
    source_result_id: Optional[int] = None
    start_seconds: Optional[float] = None
    end_seconds: Optional[float] = None
    title: str = ""
    title_text: Optional[str] = None
    description_text: Optional[str] = None
    tags_text: Optional[str] = None


@router.get("/exports")
def list_exports(episode_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = select(ExportRecord)
    if episode_id:
        query = query.where(ExportRecord.episode_id == episode_id)
    return {"exports": [row_to_dict(e) for e in db.scalars(query.order_by(ExportRecord.id.desc())).all()]}


@router.post("/exports", status_code=201)
def create_export(payload: ExportCreate, episode_id: int, db: Session = Depends(get_db)):
    data = payload.model_dump()
    meta = {k: data.pop(k) for k in ("title_text", "description_text", "tags_text") if data.get(k)}
    export = pp.create_export(db, episode_id, data.pop("kind"), **data, **meta)
    return row_to_dict(export)


@router.post("/exports/{export_id}/status")
def set_export_status(export_id: int, status: str, db: Session = Depends(get_db)):
    allowed = {"draft", "queued", "rendering", "completed", "failed", "cancelled",
               "needs_review", "approved", "rejected", "exported"}
    if status not in allowed:
        raise HTTPException(422, f"status must be one of {sorted(allowed)}")
    export = db.get(ExportRecord, export_id)
    if export is None:
        raise HTTPException(404, "Export not found")
    export.status = status
    db.commit(); db.refresh(export)
    return row_to_dict(export)


@router.get("/episodes/{episode_id}/shorts/proposals")
def shorts_proposals(episode_id: int, db: Session = Depends(get_db)):
    """Propose short-form moments (shots with approved results, 5-60s). Proposals
    only — nothing is created or published without explicit approval."""
    from ..models import GenerationResult, Shot, Scene
    shots = db.scalars(select(Shot).join(Scene, Shot.scene_id == Scene.id)
                       .where(Scene.episode_id == episode_id).order_by(Scene.order_index, Shot.order_index)).all()
    proposals = []
    for shot in shots:
        result = db.scalar(select(GenerationResult).where(
            GenerationResult.shot_id == shot.id, GenerationResult.status == "approved")
            .order_by(GenerationResult.version_number.desc()))
        if result is None:
            continue
        duration = float(shot.duration_seconds or 6)
        if 3.0 <= duration <= 60.0:
            proposals.append({"shot_id": shot.id, "shot_ref": shot.shot_ref,
                              "title": shot.title or "Untitled shot",
                              "result_id": result.id, "duration_seconds": duration,
                              "why": "Approved standalone shot within short-form length"})
    return {"proposals": proposals, "note": "Proposals only — you approve every export."}
