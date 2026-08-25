"""Phase 6 post-production models: audio, mixer, timeline, QC, renders, exports.

Additive only — existing tables (timeline_items, voice_profiles, exports,
assets, approvals) are extended with columns; new tables live here.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

# ---------------------------------------------------------------------------
# Audio: recordings (dialogue + narration), jobs, local/cloud provider lanes
# ---------------------------------------------------------------------------

RECORDING_KINDS = ("dialogue", "narration", "sfx", "ambience", "music")
RECORDING_STATUSES = ("draft", "needs_review", "approved", "rejected")
AUDIO_JOB_STATUSES = ("draft", "queued", "submitting", "submitted", "generating",
                      "completed", "failed", "cancelled", "needs_review",
                      "approved", "rejected")


class AudioRecording(TimestampMixin, Base):
    """One version of a spoken/generated audio clip. Regeneration creates a NEW
    row (version_number + 1 per script line); previous versions are never
    overwritten or deleted."""

    __tablename__ = "audio_recordings"
    __table_args__ = (
        UniqueConstraint("script_element_id", "version_number", name="uq_recording_line_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True, index=True)
    scene_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), nullable=True, index=True)
    shot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shots.id", ondelete="SET NULL"), nullable=True, index=True)
    script_element_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("script_elements.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(default="dialogue", index=True)   # dialogue|narration
    character_id: Mapped[Optional[int]] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"), nullable=True, index=True)
    voice_profile_id: Mapped[Optional[int]] = mapped_column(ForeignKey("voice_profiles.id", ondelete="SET NULL"), nullable=True)
    provider_key: Mapped[Optional[str]] = mapped_column(nullable=True)
    text: Mapped[str] = mapped_column(default="")
    voice_settings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # style/speed/pitch/emotion
    version_number: Mapped[int] = mapped_column(default=1)
    duration_seconds: Mapped[Optional[float]] = mapped_column(nullable=True)
    storage_mode: Mapped[str] = mapped_column(default="upload")     # upload | provider_result | repo_reference
    repo_path: Mapped[Optional[str]] = mapped_column(nullable=True)
    asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(default="draft", index=True)  # draft|needs_review|approved|rejected
    is_current: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[Optional[str]] = mapped_column(nullable=True)


class AudioJob(TimestampMixin, Base):
    """Audio generation job (dialogue/narration TTS lanes). Honest statuses;
    failures recorded with codes; results never fabricated."""

    __tablename__ = "audio_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    recording_id: Mapped[Optional[int]] = mapped_column(ForeignKey("audio_recordings.id", ondelete="SET NULL"), nullable=True, index=True)
    target_kind: Mapped[str] = mapped_column(default="dialogue")    # dialogue|narration
    provider_key: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(default="draft", index=True)
    request_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    provider_job_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    result_recording_id: Mapped[Optional[int]] = mapped_column(ForeignKey("audio_recordings.id", ondelete="SET NULL"), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    usage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    submitted_at: Mapped[Optional[str]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(nullable=True)


# ---------------------------------------------------------------------------
# Mixer + timeline
# ---------------------------------------------------------------------------

TRACK_KINDS = ("video", "dialogue", "narration", "sfx", "ambience", "music")


class TimelineTrack(TimestampMixin, Base):
    """Mixer track (non-destructive: volume/mute/solo never touch sources)."""

    __tablename__ = "timeline_tracks"
    __table_args__ = (UniqueConstraint("episode_id", "kind", "name", name="uq_track_episode_kind_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(default="video", index=True)
    name: Mapped[str] = mapped_column(default="")
    volume: Mapped[float] = mapped_column(default=1.0)     # 0..2 linear gain
    muted: Mapped[bool] = mapped_column(default=False)
    solo: Mapped[bool] = mapped_column(default=False)
    order_index: Mapped[int] = mapped_column(default=0)

    items: Mapped[list["TimelineItem"]] = relationship(back_populates="track_ref")


# timeline_items gains: track_id, source_type, source_id, trim_in, trim_out,
# volume_gain, fade_in, fade_out, locked (additive columns, see db.py)


# ---------------------------------------------------------------------------
# QC + renders + exports/shorts
# ---------------------------------------------------------------------------

class EpisodeRender(TimestampMixin, Base):
    """Episode render queue row + versioned output (never overwritten)."""

    __tablename__ = "episode_renders"
    __table_args__ = (UniqueConstraint("episode_id", "version_number", name="uq_render_episode_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(default="draft", index=True)
    # draft|queued|rendering|completed|failed|cancelled|needs_review|approved|rejected
    resolution: Mapped[str] = mapped_column(default="1280x720")
    fps: Mapped[float] = mapped_column(default=24.0)
    aspect_ratio: Mapped[str] = mapped_column(default="16:9")
    audio_settings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(nullable=True)
    output_path: Mapped[Optional[str]] = mapped_column(nullable=True)
    error: Mapped[Optional[str]] = mapped_column(nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    qc_overrides: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # {finding_key: explanation}
    render_log: Mapped[Optional[str]] = mapped_column(nullable=True)
    started_at: Mapped[Optional[str]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(nullable=True)


RENDER_STATUSES = ("draft", "queued", "rendering", "completed", "failed", "cancelled",
                   "needs_review", "approved", "rejected")

EXPORT_KINDS = ("full_episode", "trailer", "short_vertical", "clip_horizontal", "clip_vertical")
EXPORT_STATUSES = ("draft", "queued", "rendering", "completed", "failed", "cancelled",
                   "needs_review", "approved", "rejected", "exported")

# exports gains: render_id, source_result_id, start/end, format, output_path,
# duration, error, caption, title_text, description_text, tags_text (additive)
