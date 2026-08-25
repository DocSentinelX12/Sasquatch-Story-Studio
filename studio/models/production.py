"""Production hierarchy: Project → Season → Episode → Act → Scene → Shot."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import (
    Base,
    EpisodeStatus,
    ProjectStatus,
    SceneStatus,
    ShotStatus,
    TimestampMixin,
)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    slug: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[str] = mapped_column(default="")
    series_premise: Mapped[str] = mapped_column(default="")
    status: Mapped[str] = mapped_column(default=ProjectStatus.ACTIVE.value)
    current_season_number: Mapped[int] = mapped_column(default=1)

    seasons: Mapped[list["Season"]] = relationship(back_populates="project", order_by="Season.number")
    episodes: Mapped[list["Episode"]] = relationship(back_populates="project", order_by="Episode.number")
    characters: Mapped[list["Character"]] = relationship(  # noqa: F821
        back_populates="project", order_by="Character.name"
    )
    locations: Mapped[list["Location"]] = relationship(back_populates="project")  # noqa: F821
    props: Mapped[list["Prop"]] = relationship(back_populates="project")  # noqa: F821
    assets: Mapped[list["Asset"]] = relationship(back_populates="project")  # noqa: F821


class Season(TimestampMixin, Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_season_project_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(default=1)
    title: Mapped[str] = mapped_column(default="")
    status: Mapped[str] = mapped_column(default="planned")

    project: Mapped[Project] = relationship(back_populates="seasons")
    episodes: Mapped[list["Episode"]] = relationship(back_populates="season")


class Episode(TimestampMixin, Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_episode_project_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    season_id: Mapped[Optional[int]] = mapped_column(ForeignKey("seasons.id", ondelete="SET NULL"), nullable=True)
    number: Mapped[int] = mapped_column(default=1)
    title: Mapped[str] = mapped_column()
    slug: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default=EpisodeStatus.DRAFT.value, index=True)
    logline: Mapped[Optional[str]] = mapped_column(nullable=True)
    premise: Mapped[Optional[str]] = mapped_column(nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(nullable=True)
    target_length_minutes: Mapped[float] = mapped_column(default=8.0)
    story_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("stories.id", ondelete="SET NULL", use_alter=True), nullable=True, index=True
    )
    script_status: Mapped[str] = mapped_column(default="draft")   # draft | review | approved
    source_path: Mapped[Optional[str]] = mapped_column(nullable=True)  # canon JSON this row came from

    project: Mapped[Project] = relationship(back_populates="episodes")
    season: Mapped[Optional[Season]] = relationship(back_populates="episodes")
    acts: Mapped[list["Act"]] = relationship(back_populates="episode", order_by="Act.number", cascade="all, delete-orphan")
    scenes: Mapped[list["Scene"]] = relationship(back_populates="episode", order_by="Scene.order_index", cascade="all, delete-orphan")


class Act(TimestampMixin, Base):
    __tablename__ = "acts"
    __table_args__ = (UniqueConstraint("episode_id", "number", name="uq_act_episode_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(default=1)
    title: Mapped[str] = mapped_column(default="")
    purpose: Mapped[Optional[str]] = mapped_column(nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(nullable=True)
    beginning: Mapped[Optional[str]] = mapped_column(nullable=True)
    middle: Mapped[Optional[str]] = mapped_column(nullable=True)
    ending: Mapped[Optional[str]] = mapped_column(nullable=True)

    episode: Mapped[Episode] = relationship(back_populates="acts")
    scenes: Mapped[list["Scene"]] = relationship(back_populates="act")


class Scene(TimestampMixin, Base):
    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), index=True)
    act_id: Mapped[Optional[int]] = mapped_column(ForeignKey("acts.id", ondelete="SET NULL"), nullable=True)
    number: Mapped[int] = mapped_column(default=1)
    scene_ref: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)   # e.g. SC-001
    title: Mapped[Optional[str]] = mapped_column(nullable=True)
    slug: Mapped[Optional[str]] = mapped_column(nullable=True)
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"), nullable=True)
    time_of_day: Mapped[Optional[str]] = mapped_column(nullable=True)
    weather: Mapped[Optional[str]] = mapped_column(nullable=True)
    story_purpose: Mapped[Optional[str]] = mapped_column(nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(nullable=True)
    visual_action: Mapped[Optional[str]] = mapped_column(nullable=True)
    emotional_tone: Mapped[Optional[str]] = mapped_column(nullable=True)
    visual_direction: Mapped[Optional[str]] = mapped_column(nullable=True)
    continuity_notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    dependency_notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    estimated_duration_seconds: Mapped[Optional[float]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default=SceneStatus.DRAFT.value)
    order_index: Mapped[int] = mapped_column(default=0)
    source_path: Mapped[Optional[str]] = mapped_column(nullable=True)

    episode: Mapped[Episode] = relationship(back_populates="scenes")
    act: Mapped[Optional[Act]] = relationship(back_populates="scenes")
    location: Mapped[Optional["Location"]] = relationship(back_populates="scenes")  # noqa: F821
    shots: Mapped[list["Shot"]] = relationship(back_populates="scene", order_by="Shot.order_index", cascade="all, delete-orphan")
    storyboard: Mapped[Optional["Storyboard"]] = relationship(  # noqa: F821
        back_populates="scene", uselist=False, cascade="all, delete-orphan"
    )
    cast: Mapped[list["SceneCharacter"]] = relationship(  # noqa: F821
        back_populates="scene", cascade="all, delete-orphan", order_by="SceneCharacter.id"
    )
    prop_links: Mapped[list["SceneProp"]] = relationship(  # noqa: F821
        back_populates="scene", cascade="all, delete-orphan", order_by="SceneProp.id"
    )
    script_elements: Mapped[list["ScriptElement"]] = relationship(  # noqa: F821
        back_populates="scene", cascade="all, delete-orphan", order_by="ScriptElement.order_index, ScriptElement.id"
    )


class Shot(TimestampMixin, Base):
    __tablename__ = "shots"

    id: Mapped[int] = mapped_column(primary_key=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    shot_ref: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)  # e.g. SHOT-001
    number: Mapped[int] = mapped_column(default=1)
    title: Mapped[Optional[str]] = mapped_column(nullable=True)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    shot_type: Mapped[Optional[str]] = mapped_column(nullable=True)       # wide / medium / close-up ...
    camera_angle: Mapped[Optional[str]] = mapped_column(nullable=True)
    camera_movement: Mapped[Optional[str]] = mapped_column(nullable=True)
    camera_notes: Mapped[Optional[str]] = mapped_column(nullable=True)    # natural-language direction
    lens_framing: Mapped[Optional[str]] = mapped_column(nullable=True)
    composition: Mapped[Optional[str]] = mapped_column(nullable=True)
    subject_position: Mapped[Optional[str]] = mapped_column(nullable=True)
    duration_seconds: Mapped[float] = mapped_column(default=6.0)
    action: Mapped[Optional[str]] = mapped_column(nullable=True)
    character_action: Mapped[Optional[str]] = mapped_column(nullable=True)
    facial_expression: Mapped[Optional[str]] = mapped_column(nullable=True)
    environment_action: Mapped[Optional[str]] = mapped_column(nullable=True)
    dialogue: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)
    narration: Mapped[Optional[str]] = mapped_column(nullable=True)
    sound_effects: Mapped[Optional[str]] = mapped_column(JSON, nullable=True)
    music: Mapped[Optional[str]] = mapped_column(nullable=True)
    transition: Mapped[Optional[str]] = mapped_column(nullable=True)
    visual_style: Mapped[Optional[str]] = mapped_column(nullable=True)
    lighting: Mapped[Optional[str]] = mapped_column(nullable=True)
    weather: Mapped[Optional[str]] = mapped_column(nullable=True)
    continuity_notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    # dependency state (PART 10) — free-form state carried across shots
    character_state_notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    prop_state_notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    location_state_notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    prev_shot_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    next_shot_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    generation_status: Mapped[str] = mapped_column(default="pending")   # pending | generating | generated | failed
    status: Mapped[str] = mapped_column(default=ShotStatus.DRAFT.value)
    order_index: Mapped[int] = mapped_column(default=0)
    source_path: Mapped[Optional[str]] = mapped_column(nullable=True)

    scene: Mapped[Scene] = relationship(back_populates="shots")
    generation_jobs: Mapped[list["GenerationJob"]] = relationship(  # noqa: F821
        back_populates="shot"
    )
    cast: Mapped[list["ShotCharacter"]] = relationship(  # noqa: F821
        back_populates="shot", cascade="all, delete-orphan", order_by="ShotCharacter.id"
    )
    prop_links: Mapped[list["ShotProp"]] = relationship(  # noqa: F821
        back_populates="shot", cascade="all, delete-orphan", order_by="ShotProp.id"
    )
    references: Mapped[list["ShotReference"]] = relationship(  # noqa: F821
        back_populates="shot", cascade="all, delete-orphan", order_by="ShotReference.order_index"
    )
    versions: Mapped[list["ShotVersion"]] = relationship(  # noqa: F821
        back_populates="shot", cascade="all, delete-orphan", order_by="ShotVersion.version_number"
    )
    continuity_records: Mapped[list["ShotContinuity"]] = relationship(  # noqa: F821
        back_populates="shot", cascade="all, delete-orphan"
    )
