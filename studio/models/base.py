"""Model base classes and shared value enumerations."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --- Shared vocabularies (kept aligned with the JSON content system) ---------

class ProjectStatus(str, Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class EpisodeStatus(str, Enum):
    PLANNED = "planned"
    OUTLINE = "outline"
    SCRIPT = "script"
    STORYBOARD = "storyboard"
    SHOT_BUILDING = "shot_building"
    GENERATING = "generating"
    EDITING = "editing"
    QC = "qc"
    EXPORTED = "exported"
    RELEASED = "released"


class SceneStatus(str, Enum):
    PLANNED = "planned"
    WRITTEN = "written"
    BOARDED = "boarded"
    SHOT_READY = "shot_ready"
    GENERATING = "generating"
    APPROVED = "approved"


class ShotStatus(str, Enum):
    PLANNED = "planned"
    READY = "ready"
    QUEUED = "queued"
    GENERATING = "generating"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class AssetCategory(str, Enum):
    CHARACTER = "characters"
    CHARACTER_REFERENCE = "character_references"
    EXPRESSION = "expressions"
    POSE = "poses"
    ENVIRONMENT = "environments"
    BACKGROUND = "backgrounds"
    PROP = "props"
    VEHICLE = "vehicles"
    ANIMAL = "animals"
    TEXTURE = "textures"
    IMAGE = "images"
    MUSIC = "music"
    SOUND_EFFECT = "sound_effects"
    VOICE = "voice"
    VIDEO = "video"
    OTHER = "other"


class AssetClass(str, Enum):
    """Same vocabulary as assets/asset-manifest.json."""
    CREATOR_SOURCE_ARTWORK = "creator_source_artwork"
    APPROVED_CANON_REFERENCE = "approved_canon_reference"
    AI_GENERATED_TEST_MATERIAL = "ai_generated_test_material"
    PRODUCTION_MATERIAL = "production_material"
    UNCLASSIFIED = "unclassified"


class AssetStorageMode(str, Enum):
    REPO_REFERENCE = "repo_reference"   # file lives in the repository; app never modifies it
    UPLOAD = "upload"                   # app-managed file under assets/studio-uploads/
    PROVIDER_RESULT = "provider_result" # downloaded generation output


class AssetStatus(str, Enum):
    REGISTERED = "registered"            # a.k.a. Draft in the UI
    PENDING_APPROVAL = "pending_approval"  # a.k.a. In Review
    APPROVED = "approved"
    REJECTED = "rejected"
    OBSOLETE = "obsolete"                # a.k.a. Archived


class AssetProvenance(str, Enum):
    CREATOR = "creator"
    META_AI = "meta_ai"
    PROVIDER = "provider"
    STUDIO = "studio"
    OTHER = "other"


class ApprovalStatus(str, Enum):
    REGISTERED = "registered"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"


class JobStatus(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class MediaKind(str, Enum):
    VIDEO = "video"
    IMAGE = "image"
    ANIMATION_TEST = "animation_test"


class ProviderKind(str, Enum):
    VIDEO = "video"
    VOICE = "voice"
    MUSIC = "music"
    IMAGE = "image"


class ProviderStatus(str, Enum):
    NOT_CONFIGURED = "not_configured"
    READY = "ready"
    ERROR = "error"


class AudioKind(str, Enum):
    DIALOGUE = "dialogue"
    NARRATION = "narration"
    MUSIC = "music"
    SFX = "sfx"
    AMBIENT = "ambient"


class ExportKind(str, Enum):
    FULL_EPISODE = "full_episode"
    TRAILER = "trailer"
    SHORT_VERTICAL = "short_vertical"
    CLIP_HORIZONTAL = "clip_horizontal"
    CLIP_VERTICAL = "clip_vertical"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class ContinuityKind(str, Enum):
    EVENT = "event"
    CHARACTER_LOCATION = "character_location"
    RELATIONSHIP = "relationship"
    PROP = "prop"
    INJURY = "injury"
    CLOTHING = "clothing"
    WEATHER = "weather"
    TIME_OF_DAY = "time_of_day"
    DISCOVERY = "discovery"
    OPEN_THREAD = "open_thread"
    CANON_FACT = "canon_fact"


# JSON column helper (SQLite stores TEXT)
from sqlalchemy import JSON  # noqa: E402


class JSONList(list):
    """Marker used by row serializers; plain lists are fine as JSON values."""
