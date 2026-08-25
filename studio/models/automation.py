"""Phase 8 models: automation rules, audit log, notifications, templates."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, JSON, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

# Triggers (WHEN) — safe, audited events emitted by the studio
AUTOMATION_TRIGGERS = (
    "shot_approved",            # a shot's video result was approved
    "audio_approved",           # an audio recording was approved
    "scene_complete",           # every shot in a scene has an approved result
    "episode_ready",            # episode QC reaches pass/warning (not blocked)
    "generation_failed",        # a generation job failed
    "generation_succeeded",     # a generation job completed
    "qc_warning",               # QC produced warnings
    "qc_blocker",               # QC produced blockers
)

# Actions (THEN) — automation may PREPARE or QUEUE work, never approve/publish
AUTOMATION_ACTIONS = (
    "queue_next_shot",          # queue generation for the next ready shot
    "queue_missing_audio",      # queue generation for missing dialogue/narration
    "run_qc",                   # run episode QC and record the result
    "prepare_render",           # create a DRAFT render (never queues/publishes)
    "notify_user",              # create a notification
    "pause_production",         # pause batch production for the series
    "mark_episode_review",      # flag the episode for human review
)

RULE_CONDITION_FIELDS = ("episode_id", "scene_id", "shot_id", "min_shots_approved",
                         "max_blocking", "max_warnings")


class AutomationRule(TimestampMixin, Base):
    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)  # null = all series
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    trigger: Mapped[str] = mapped_column(index=True)
    conditions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    actions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)   # [{action, params}]
    priority: Mapped[int] = mapped_column(default=5)                       # lower runs first
    dry_run: Mapped[bool] = mapped_column(default=False)
    run_count: Mapped[int] = mapped_column(default=0)
    last_run_at: Mapped[Optional[str]] = mapped_column(nullable=True)


class AutomationAudit(TimestampMixin, Base):
    """Every automated action is logged — nothing hidden."""
    __tablename__ = "automation_audit"
    __table_args__ = (Index("ix_autoaudit_rule", "rule_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("automation_rules.id", ondelete="SET NULL"), nullable=True)
    rule_name: Mapped[str] = mapped_column(default="(manual)")
    trigger_event: Mapped[str] = mapped_column(default="")
    target: Mapped[Optional[str]] = mapped_column(nullable=True)         # e.g. "Scene 4" / "EP-001"
    dry_run: Mapped[bool] = mapped_column(default=False)
    actions_taken: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # [{action, result}]
    outcome: Mapped[Optional[str]] = mapped_column(nullable=True)


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(default="info")      # info | warning | blocker | automation
    message: Mapped[str] = mapped_column()
    link: Mapped[Optional[str]] = mapped_column(nullable=True)
    read: Mapped[bool] = mapped_column(default=False)


class EpisodeTemplate(TimestampMixin, Base):
    """Reusable episode structure (acts/scenes/shots/scripts copied as drafts)."""
    __tablename__ = "episode_templates"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_template_project_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    source_episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True)
    structure: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # acts/scenes/shots/script skeleton
