"""Voice, audio-track and timeline models (tables ready for later phases)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class VoiceProfile(TimestampMixin, Base):
    __tablename__ = "voice_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("characters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column()
    role: Mapped[str] = mapped_column(default="character")     # character | narrator
    provider_key: Mapped[Optional[str]] = mapped_column(nullable=True)  # future voice providers
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    settings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(default="draft")       # draft | pending_approval | approved

    character = relationship("Character", back_populates="voice_profiles")


class AudioTrack(TimestampMixin, Base):
    __tablename__ = "audio_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True, index=True)
    scene_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), nullable=True, index=True)
    shot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(default="dialogue")   # dialogue|narration|music|sfx|ambient
    title: Mapped[str] = mapped_column(default="")
    asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    storage_mode: Mapped[Optional[str]] = mapped_column(nullable=True)
    repo_path: Mapped[Optional[str]] = mapped_column(nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default="planned")  # planned|pending_approval|approved

    asset = relationship("Asset")


class TimelineItem(TimestampMixin, Base):
    __tablename__ = "timeline_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), index=True)
    track_kind: Mapped[str] = mapped_column(default="video")  # video|dialogue|narration|music|sfx|caption|marker
    label: Mapped[str] = mapped_column(default="")
    start_seconds: Mapped[float] = mapped_column(default=0.0)
    end_seconds: Mapped[float] = mapped_column(default=0.0)
    shot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shots.id", ondelete="SET NULL"), nullable=True)
    scene_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True)
    asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    order_index: Mapped[int] = mapped_column(default=0)
    transition_in: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)   # {type, duration_seconds}
    # --- Phase 6 additive: mixer + non-destructive editing ---
    track_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("timeline_tracks.id", ondelete="CASCADE"), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(default="shot_result")  # shot_result|recording|asset|gap
    source_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    trim_in: Mapped[float] = mapped_column(default=0.0)
    trim_out: Mapped[float] = mapped_column(default=0.0)
    volume_gain: Mapped[float] = mapped_column(default=1.0)
    fade_in: Mapped[float] = mapped_column(default=0.0)
    fade_out: Mapped[float] = mapped_column(default=0.0)
    locked: Mapped[bool] = mapped_column(default=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    track_ref: Mapped[Optional["TimelineTrack"]] = relationship(back_populates="items")  # noqa: F821
    shot_ref: Mapped[Optional["Shot"]] = relationship(back_populates="timeline_items")   # noqa: F821
