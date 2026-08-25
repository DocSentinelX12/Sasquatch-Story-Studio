"""Character, location, prop, asset and asset-version models."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import (
    ApprovalStatus,
    AssetCategory,
    AssetClass,
    AssetProvenance,
    AssetStatus,
    AssetStorageMode,
    Base,
    TimestampMixin,
)


class Character(TimestampMixin, Base):
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("project_id", "char_ref", name="uq_character_project_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    char_ref: Mapped[Optional[str]] = mapped_column(nullable=True)        # e.g. CHAR-YETI (repo vocabulary)
    name: Mapped[str] = mapped_column(index=True)
    role: Mapped[Optional[str]] = mapped_column(nullable=True)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    species: Mapped[Optional[str]] = mapped_column(nullable=True)
    family_ref: Mapped[Optional[str]] = mapped_column(nullable=True)      # e.g. FAMILY-BIG-CEDAR
    character_kind: Mapped[str] = mapped_column(default="person")        # person | animal
    age_group: Mapped[Optional[str]] = mapped_column(nullable=True)
    approximate_age: Mapped[Optional[str]] = mapped_column(nullable=True)
    personality_summary: Mapped[Optional[str]] = mapped_column(nullable=True)
    appearance_summary: Mapped[Optional[str]] = mapped_column(nullable=True)
    clothing: Mapped[Optional[str]] = mapped_column(nullable=True)
    colors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    height_proportions: Mapped[Optional[str]] = mapped_column(nullable=True)
    voice_notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    master_visual_prompt: Mapped[Optional[str]] = mapped_column(nullable=True)
    negative_prompt: Mapped[Optional[str]] = mapped_column(nullable=True)
    continuity_rules: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # --- Phase 2: continuity foundation (consumed later by Scene/Shot systems)
    standard_appearance: Mapped[Optional[str]] = mapped_column(nullable=True)
    current_outfit: Mapped[Optional[str]] = mapped_column(nullable=True)
    standard_props: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    personality_rules: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    visual_rules: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    never_changes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # Lifecycle is separate from canon approval:
    #   life_status: draft | active | archived   (archive never deletes source assets)
    #   approval_status: registered | pending_approval | approved
    life_status: Mapped[str] = mapped_column(default="draft", index=True)
    approval_status: Mapped[str] = mapped_column(default=ApprovalStatus.REGISTERED.value)
    is_canon: Mapped[bool] = mapped_column(default=False)   # seeded from / verified against creator canon
    source_path: Mapped[Optional[str]] = mapped_column(nullable=True)  # bible record JSON

    project = relationship("Project", back_populates="characters")
    references: Mapped[list["CharacterReference"]] = relationship(
        back_populates="character", cascade="all, delete-orphan"
    )
    outgoing_relationships: Mapped[list["CharacterRelationship"]] = relationship(
        "CharacterRelationship",
        foreign_keys="CharacterRelationship.character_id",
        back_populates="character",
        cascade="all, delete-orphan",
    )
    incoming_relationships: Mapped[list["CharacterRelationship"]] = relationship(
        "CharacterRelationship",
        foreign_keys="CharacterRelationship.related_character_id",
        back_populates="related",
        cascade="all, delete-orphan",
    )
    bible: Mapped[Optional["CharacterBible"]] = relationship(  # noqa: F821
        back_populates="character", uselist=False, cascade="all, delete-orphan"
    )
    voice_profiles: Mapped[list["VoiceProfile"]] = relationship(  # noqa: F821
        back_populates="character"
    )


# Reference categories a production reference can belong to.
REFERENCE_PURPOSES = {
    "primary", "full_body", "face", "expression", "pose", "side_view",
    "back_view", "action_pose", "outfit", "prop_reference", "other",
    # legacy Phase 1 values kept valid for existing rows
    "identity", "turnaround", "scale", "clothing", "color",
}

REFERENCE_STATUSES = {"registered", "pending_approval", "approved"}


class CharacterReference(TimestampMixin, Base):
    __tablename__ = "character_references"

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(default="primary")
    label: Mapped[Optional[str]] = mapped_column(nullable=True)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    is_primary: Mapped[bool] = mapped_column(default=False)
    approval_status: Mapped[str] = mapped_column(default=ApprovalStatus.REGISTERED.value)

    character: Mapped[Character] = relationship(back_populates="references")
    asset: Mapped["Asset"] = relationship(back_populates="character_links")


class CharacterRelationship(TimestampMixin, Base):
    """Directed relationship between two characters (Phase 2).

    kind: friend | family | enemy | companion | neighbor | recurring | mentor | other
    """

    __tablename__ = "character_relationships"
    __table_args__ = (
        UniqueConstraint("character_id", "related_character_id", "kind", name="uq_relationship_triple"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    related_character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(default="other")
    notes: Mapped[Optional[str]] = mapped_column(nullable=True)

    character: Mapped[Character] = relationship(
        "Character", foreign_keys=[character_id], back_populates="outgoing_relationships"
    )
    related: Mapped[Character] = relationship(
        "Character", foreign_keys=[related_character_id], back_populates="incoming_relationships"
    )


class AssetTag(TimestampMixin, Base):
    """Tag index for fast filtering/browsing (assets.tags JSON stays the source
    of truth; this table is kept in sync by the API layer)."""

    __tablename__ = "asset_tags"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_asset_tag_project_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(index=True)


class Location(TimestampMixin, Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    loc_ref: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)   # e.g. LOC-BIG-CEDAR-HOME
    name: Mapped[str] = mapped_column()
    kind: Mapped[Optional[str]] = mapped_column(nullable=True)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    source_path: Mapped[Optional[str]] = mapped_column(nullable=True)

    project = relationship("Project", back_populates="locations")
    scenes = relationship("Scene", back_populates="location")


class Prop(TimestampMixin, Base):
    __tablename__ = "props"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    source_path: Mapped[Optional[str]] = mapped_column(nullable=True)

    project = relationship("Project", back_populates="props")


class Asset(TimestampMixin, Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(default=AssetCategory.OTHER.value, index=True)
    title: Mapped[str] = mapped_column()
    original_filename: Mapped[Optional[str]] = mapped_column(nullable=True)
    storage_mode: Mapped[str] = mapped_column(default=AssetStorageMode.UPLOAD.value)
    repo_path: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)  # repo-relative file path
    mime_type: Mapped[Optional[str]] = mapped_column(nullable=True)
    byte_size: Mapped[Optional[int]] = mapped_column(nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(nullable=True, index=True)
    asset_class: Mapped[str] = mapped_column(default=AssetClass.UNCLASSIFIED.value)
    provenance: Mapped[str] = mapped_column(default=AssetProvenance.OTHER.value)
    status: Mapped[str] = mapped_column(default=AssetStatus.PENDING_APPROVAL.value, index=True)
    is_favorite: Mapped[bool] = mapped_column(default=False)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    character_id: Mapped[Optional[int]] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"), nullable=True)
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True)
    scene_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True)
    current_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("asset_versions.id", use_alter=True, ondelete="SET NULL"), nullable=True
    )

    project = relationship("Project", back_populates="assets")
    character = relationship("Character")
    location = relationship("Location")
    episode = relationship("Episode")
    scene = relationship("Scene")
    versions: Mapped[list["AssetVersion"]] = relationship(
        back_populates="asset",
        order_by="AssetVersion.version_number",
        cascade="all, delete-orphan",
        foreign_keys="AssetVersion.asset_id",
    )
    character_links: Mapped[list[CharacterReference]] = relationship(back_populates="asset")


class AssetVersion(TimestampMixin, Base):
    __tablename__ = "asset_versions"
    __table_args__ = (UniqueConstraint("asset_id", "version_number", name="uq_assetversion_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(default=1)
    storage_mode: Mapped[str] = mapped_column(default=AssetStorageMode.UPLOAD.value)
    repo_path: Mapped[Optional[str]] = mapped_column(nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(nullable=True)
    byte_size: Mapped[Optional[int]] = mapped_column(nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(default="upload")  # upload | repo_scan | provider | replace
    notes: Mapped[Optional[str]] = mapped_column(nullable=True)
    is_current: Mapped[bool] = mapped_column(default=True)
    # Version-level review state (same vocabulary as AssetStatus):
    # registered(draft) | pending_approval(review) | approved | rejected | obsolete(archived)
    status: Mapped[str] = mapped_column(default="registered")

    asset: Mapped[Asset] = relationship(back_populates="versions", foreign_keys=[asset_id])
