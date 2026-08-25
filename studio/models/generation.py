"""Generation providers, jobs and results."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, JobStatus, MediaKind, ProviderKind, ProviderStatus, TimestampMixin, utcnow


class Provider(TimestampMixin, Base):
    """Mirror of the code-level provider registry (studio/providers/registry.py).

    Status is recomputed from the server environment; this row stores the
    user-visible configuration and documentation.
    """

    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(unique=True, index=True)          # seedance | veo | wan | ...
    display_name: Mapped[str] = mapped_column()
    kind: Mapped[str] = mapped_column(default=ProviderKind.VIDEO.value)
    status: Mapped[str] = mapped_column(default=ProviderStatus.NOT_CONFIGURED.value)
    required_env: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)   # names only, never values
    capabilities: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    docs_url: Mapped[Optional[str]] = mapped_column(nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    adapter_module: Mapped[Optional[str]] = mapped_column(nullable=True)


class GenerationJob(TimestampMixin, Base):
    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True, index=True)
    scene_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True, index=True)
    shot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shots.id", ondelete="SET NULL"), nullable=True, index=True)
    provider_key: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    media_kind: Mapped[str] = mapped_column(default=MediaKind.VIDEO.value)
    status: Mapped[str] = mapped_column(default=JobStatus.DRAFT.value, index=True)
    priority: Mapped[int] = mapped_column(default=1)   # 0=urgent 1=high? see PRIORITY_MAP
    title: Mapped[str] = mapped_column(default="")
    # Normalized, provider-neutral prompt package:
    #   {positive_prompt, negative_constraints, reference_images: [{asset_id,
    #   entity_id, purpose, asset_class, repo_path, sha256, order}], continuity_notes}
    prompt_package: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    settings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    provider_job_id: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    attempt: Mapped[int] = mapped_column(default=1)
    package_version: Mapped[Optional[int]] = mapped_column(nullable=True)
    translated_request: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    submitted_references: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    usage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    poll_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    project = relationship("Project")
    episode = relationship("Episode")
    scene = relationship("Scene")
    shot = relationship("Shot", back_populates="generation_jobs")
    results: Mapped[list["GenerationResult"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class GenerationResult(TimestampMixin, Base):
    __tablename__ = "generation_results"
    __table_args__ = (UniqueConstraint("job_id", "version_number", name="uq_result_job_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("generation_jobs.id", ondelete="CASCADE"), index=True)
    shot_id: Mapped[Optional[int]] = mapped_column(nullable=True, index=True)
    provider_key: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    version_number: Mapped[int] = mapped_column(default=1)
    storage_mode: Mapped[Optional[str]] = mapped_column(nullable=True)
    repo_path: Mapped[Optional[str]] = mapped_column(nullable=True)
    uri: Mapped[Optional[str]] = mapped_column(nullable=True)
    checksum: Mapped[Optional[str]] = mapped_column(nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default="needs_review")  # needs_review|approved|rejected
    file_size: Mapped[Optional[int]] = mapped_column(nullable=True)
    provider_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_approved: Mapped[bool] = mapped_column(default=False)  # approval-first: never auto-true

    job: Mapped[GenerationJob] = relationship(back_populates="results")
