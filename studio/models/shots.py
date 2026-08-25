"""Phase 4: storyboards, shot casting/references, versions, prompt packages."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

# Phase 4 shot lifecycle (PART 13). Legacy Phase 1 values normalize on write.
SHOT_STATUSES = (
    "draft", "needs_review", "approved", "ready_for_generation",
    "generating", "generated", "needs_revision", "rejected", "complete",
)

SHOT_TYPES = (
    "extreme_wide", "wide", "full", "medium", "medium_close_up", "close_up",
    "extreme_close_up", "over_the_shoulder", "two_shot", "insert",
    "establishing", "pov", "custom",
)

CAMERA_ANGLES = (
    "eye_level", "low_angle", "high_angle", "birds_eye", "worms_eye",
    "dutch_angle", "overhead", "custom",
)

CAMERA_MOVEMENTS = (
    "static", "pan", "tilt", "push_in", "pull_out", "dolly", "tracking",
    "orbit", "crane", "handheld", "custom",
)

# Reference purposes for shot-attached assets (PART 11 + 12)
SHOT_REFERENCE_PURPOSES = (
    "first_frame", "last_frame", "keyframe", "prev_shot_frame", "next_shot_frame",
    "storyboard_image", "character_reference", "location_reference",
    "prop_reference", "other",
)


class Storyboard(TimestampMixin, Base):
    """One storyboard per scene (PART 1)."""

    __tablename__ = "storyboards"
    __table_args__ = (UniqueConstraint("scene_id", name="uq_storyboard_scene"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    board_status: Mapped[str] = mapped_column(default="draft")   # draft | in_progress | approved
    notes: Mapped[Optional[str]] = mapped_column(nullable=True)

    scene = relationship("Scene", back_populates="storyboard")


class ShotCharacter(TimestampMixin, Base):
    """Casting link: character appears in a shot (PART 5)."""

    __tablename__ = "shot_characters"
    __table_args__ = (UniqueConstraint("shot_id", "character_id", name="uq_shot_character"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shot_id: Mapped[int] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    role_in_shot: Mapped[Optional[str]] = mapped_column(nullable=True)
    expression_note: Mapped[Optional[str]] = mapped_column(nullable=True)
    action_note: Mapped[Optional[str]] = mapped_column(nullable=True)

    character = relationship("Character")
    shot = relationship("Shot", back_populates="cast")


class ShotProp(TimestampMixin, Base):
    """Prop appearing in a shot (PART 7)."""

    __tablename__ = "shot_props"
    __table_args__ = (UniqueConstraint("shot_id", "prop_id", name="uq_shot_prop"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shot_id: Mapped[int] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), index=True)
    prop_id: Mapped[int] = mapped_column(ForeignKey("props.id", ondelete="CASCADE"), index=True)
    usage_notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    state_notes: Mapped[Optional[str]] = mapped_column(nullable=True)   # prop state dependency

    prop = relationship("Prop")
    shot = relationship("Shot", back_populates="prop_links")


class ShotReference(TimestampMixin, Base):
    """Asset attached to a shot: storyboard image, first/last frame, keyframes,
    character/location/prop references (PART 11 + 12)."""

    __tablename__ = "shot_references"

    id: Mapped[int] = mapped_column(primary_key=True)
    shot_id: Mapped[int] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(default="storyboard_image")
    label: Mapped[Optional[str]] = mapped_column(nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    order_index: Mapped[int] = mapped_column(default=0)

    asset = relationship("Asset")
    shot = relationship("Shot", back_populates="references")


class ShotVersion(TimestampMixin, Base):
    """Immutable snapshot of a shot's creative content (PART 15).

    Versions are append-only; approved snapshots are never silently overwritten.
    """

    __tablename__ = "shot_versions"
    __table_args__ = (UniqueConstraint("shot_id", "version_number", name="uq_shot_version_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shot_id: Mapped[int] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(default=1)
    label: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default="draft")    # draft | approved | archived
    snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # full creative fields
    is_current: Mapped[bool] = mapped_column(default=False)

    shot = relationship("Shot", back_populates="versions")


class GenerationPromptPackage(TimestampMixin, Base):
    """Assembled, provider-neutral generation package for a shot (PART 8 + 19).
    Phase 5 submits these to video providers; nothing is sent now."""

    __tablename__ = "generation_prompt_packages"

    id: Mapped[int] = mapped_column(primary_key=True)
    shot_id: Mapped[int] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(default=1)
    package: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(default="assembly")   # assembly | override | manual


class ShotContinuity(TimestampMixin, Base):
    """Continuity warning records + explicit overrides for a shot (PART 9 + 14).
    Warnings are recorded, never auto-fixed."""

    __tablename__ = "shot_continuity"

    id: Mapped[int] = mapped_column(primary_key=True)
    shot_id: Mapped[int] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), index=True)
    check_key: Mapped[str] = mapped_column(index=True)        # e.g. character-reference:CHAR-YETI
    severity: Mapped[str] = mapped_column(default="warning")  # error | warning | info
    message: Mapped[str] = mapped_column(default="")
    overridden: Mapped[bool] = mapped_column(default=False)
    override_explanation: Mapped[Optional[str]] = mapped_column(nullable=True)
    overridden_at: Mapped[Optional[str]] = mapped_column(nullable=True)  # ISO timestamp

    shot = relationship("Shot", back_populates="continuity_records")
