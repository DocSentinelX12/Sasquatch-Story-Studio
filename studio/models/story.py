"""Phase 3 story layer: canon entries, stories, scene casting, scripts."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


# Canon categories (PART 2)
CANON_CATEGORIES = (
    "character", "world", "location", "relationship", "event", "object", "episode",
)
CANON_STATUSES = ("draft", "proposed", "canon", "deprecated")


class CanonEntry(TimestampMixin, Base):
    """A single structured canon fact. Nothing becomes 'canon' without approval."""

    __tablename__ = "canon_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(default="world", index=True)
    title: Mapped[str] = mapped_column()
    statement: Mapped[str] = mapped_column(default="")
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(default="draft", index=True)   # draft|proposed|canon|deprecated
    origin: Mapped[str] = mapped_column(default="manual")              # manual | seeded | episode
    source_path: Mapped[Optional[str]] = mapped_column(nullable=True)
    episode_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True, index=True
    )


STORY_STATUSES = ("draft", "in_development", "review", "approved", "archived")


class Story(TimestampMixin, Base):
    """A story idea developed toward an episode (PART 3 + 4).

    Core fields are columns; beats and development structure live in JSON so
    the editor can stay flexible. Nothing here is canon until approved.
    """

    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(default="Untitled Idea")
    idea_text: Mapped[str] = mapped_column(default="")
    logline: Mapped[Optional[str]] = mapped_column(nullable=True)
    premise: Mapped[Optional[str]] = mapped_column(nullable=True)
    main_conflict: Mapped[Optional[str]] = mapped_column(nullable=True)
    stakes: Mapped[Optional[str]] = mapped_column(nullable=True)
    setting: Mapped[Optional[str]] = mapped_column(nullable=True)
    beginning: Mapped[Optional[str]] = mapped_column(nullable=True)
    middle: Mapped[Optional[str]] = mapped_column(nullable=True)
    ending: Mapped[Optional[str]] = mapped_column(nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(nullable=True)
    # development (PART 4)
    goal: Mapped[Optional[str]] = mapped_column(nullable=True)
    obstacles: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    motivations: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    turning_points: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    climax: Mapped[Optional[str]] = mapped_column(nullable=True)
    # beats: {major: [], comedy: [], emotional: [], suspense: []}
    beats: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    character_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(default="draft", index=True)
    episode_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True, index=True
    )


class SceneCharacter(TimestampMixin, Base):
    """Casting link: which library characters appear in a scene (PART 8)."""

    __tablename__ = "scene_characters"
    __table_args__ = (UniqueConstraint("scene_id", "character_id", name="uq_scene_character"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    role_in_scene: Mapped[Optional[str]] = mapped_column(nullable=True)

    character = relationship("Character")
    scene = relationship("Scene", back_populates="cast")


class SceneProp(TimestampMixin, Base):
    """Which reusable props appear in a scene (PART 10)."""

    __tablename__ = "scene_props"
    __table_args__ = (UniqueConstraint("scene_id", "prop_id", name="uq_scene_prop"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    prop_id: Mapped[int] = mapped_column(ForeignKey("props.id", ondelete="CASCADE"), index=True)
    usage_notes: Mapped[Optional[str]] = mapped_column(nullable=True)

    prop = relationship("Prop")
    scene = relationship("Scene", back_populates="prop_links")


SCRIPT_ELEMENT_TYPES = (
    "scene_heading", "action", "dialogue", "narration",
    "parenthetical", "sound_cue", "camera_note", "transition",
)


class ScriptElement(TimestampMixin, Base):
    """One ordered line of a scene's script (PART 11 + 12)."""

    __tablename__ = "script_elements"

    id: Mapped[int] = mapped_column(primary_key=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    order_index: Mapped[float] = mapped_column(default=0)
    element_type: Mapped[str] = mapped_column(default="action", index=True)
    character_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("characters.id", ondelete="SET NULL"), nullable=True
    )
    character_name: Mapped[Optional[str]] = mapped_column(nullable=True)  # free-text fallback speaker
    narrator_name: Mapped[Optional[str]] = mapped_column(nullable=True)   # for narration elements
    text: Mapped[str] = mapped_column(default="")
    timing_notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    source_ref: Mapped[Optional[str]] = mapped_column(nullable=True)      # e.g. LINE-001 from canon file

    character = relationship("Character")
    scene = relationship("Scene", back_populates="script_elements")
