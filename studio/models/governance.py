"""Story/character bibles, continuity records, approvals and exports."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import ApprovalDecision, Base, TimestampMixin


class StoryBible(TimestampMixin, Base):
    __tablename__ = "story_bibles"
    __table_args__ = (UniqueConstraint("project_id", name="uq_story_bible_project"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(default="Story Bible")
    source_path: Mapped[Optional[str]] = mapped_column(nullable=True)  # series-bible/series.json
    content: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(default="draft", index=True)   # draft | approved | archived


class CharacterBible(TimestampMixin, Base):
    __tablename__ = "character_bibles"
    __table_args__ = (UniqueConstraint("character_id", name="uq_character_bible_character"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    source_path: Mapped[Optional[str]] = mapped_column(nullable=True)  # assets/characters/records/<slug>.json
    content: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # full canonical record

    character = relationship("Character", back_populates="bible")


class ContinuityRecord(TimestampMixin, Base):
    __tablename__ = "continuity_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(default="event")
    summary: Mapped[str] = mapped_column()
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(default="draft")   # draft | canon (canon only via explicit approval)
    source_path: Mapped[Optional[str]] = mapped_column(nullable=True)


class Approval(TimestampMixin, Base):
    """Generic, append-only approval ledger.

    The studio never auto-approves anything: decisions are explicit rows here.
    """

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(index=True)  # story|script|character|asset|scene|shot|generation|voice|audio|episode|export|short
    entity_id: Mapped[str] = mapped_column(index=True)    # row id or stable ref
    decision: Mapped[str] = mapped_column(default=ApprovalDecision.APPROVED.value)
    note: Mapped[Optional[str]] = mapped_column(nullable=True)


class ExportRecord(TimestampMixin, Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(default="full_episode")
    title: Mapped[str] = mapped_column(default="")
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(default="draft")  # draft|pending_approval|approved|exported
    thumbnail_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)
