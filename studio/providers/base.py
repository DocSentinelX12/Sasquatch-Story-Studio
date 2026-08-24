"""Stable internal contract for future media-generation providers.

This module performs no network calls and contains no provider implementation. A real
adapter can translate :class:`GenerationRequest` to a vendor SDK while story files
and creator-approved reference identity remain provider-neutral.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class MediaKind(str, Enum):
    """Media types the internal planning format can request."""

    VIDEO = "video"
    IMAGE = "image"
    ANIMATION_TEST = "animation_test"


class JobState(str, Enum):
    """Normalized lifecycle states independent of a provider's terminology."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReferenceAssetClass(str, Enum):
    """The only asset classes allowed to control character identity."""

    CREATOR_SOURCE_ARTWORK = "creator_source_artwork"
    APPROVED_CANON_REFERENCE = "approved_canon_reference"


class ReferencePurpose(str, Enum):
    """Provider-neutral reason an approved image is included in a request."""

    IDENTITY = "identity"
    TURNAROUND = "turnaround"
    EXPRESSION = "expression"
    POSE = "pose"
    SCALE = "scale"
    CLOTHING = "clothing"
    COLOR = "color"
    LOCATION = "location"
    PROP = "prop"


@dataclass(frozen=True)
class ReferenceImage:
    """A manifest-resolved, explicitly approved image passed to an adapter.

    AI-generated test material cannot be represented by ``ReferenceAssetClass`` and
    therefore cannot silently enter a character identity request.
    """

    asset_id: str
    entity_id: str
    purpose: ReferencePurpose
    asset_class: ReferenceAssetClass
    uri_or_path: str
    sha256: str
    approval_status: str
    order: int
    notes: str | None = None


@dataclass(frozen=True)
class GenerationRequest:
    """A validated shot request passed from episode content to an adapter."""

    request_id: str
    episode_id: str
    scene_id: str
    shot_id: str
    media_kind: MediaKind
    duration_seconds: float
    aspect_ratio: str
    positive_prompt: Mapping[str, str]
    negative_constraints: tuple[str, ...]
    reference_images: tuple[ReferenceImage, ...] = ()
    provider_overrides: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderJob:
    """Normalized handle returned after a real adapter accepts a request."""

    provider_name: str
    provider_job_id: str
    request_id: str
    state: JobState
    detail: str | None = None


@dataclass(frozen=True)
class GeneratedAsset:
    """Provider result metadata; binary storage is handled outside the adapter."""

    asset_id: str
    request_id: str
    provider_name: str
    provider_model: str
    media_kind: MediaKind
    uri_or_path: str
    checksum: str | None = None
    provider_request_id: str | None = None
    source_reference_asset_ids: tuple[str, ...] = ()
    asset_class: str = "ai_generated_test_material"
    metadata: Mapping[str, Any] = field(default_factory=dict)


class UnsupportedRequest(ValueError):
    """Raised when an adapter cannot safely represent a normalized request."""


def validate_reference_images(request: GenerationRequest) -> tuple[str, ...]:
    """Return authority/approval errors before a provider adapter sees a request."""

    errors: list[str] = []
    seen_orders: set[int] = set()
    for reference in request.reference_images:
        if reference.approval_status != "approved_for_reference":
            errors.append(
                f"{reference.asset_id} is not explicitly approved_for_reference"
            )
        if reference.order in seen_orders:
            errors.append(f"reference image order {reference.order} is duplicated")
        seen_orders.add(reference.order)
        if len(reference.sha256) != 64:
            errors.append(f"{reference.asset_id} has no valid SHA-256 checksum")
    return tuple(errors)


@runtime_checkable
class GenerationProvider(Protocol):
    """Interface a future Seedance, Veo, Higgsfield, or other adapter implements."""

    @property
    def name(self) -> str:
        """Stable adapter name used in production provenance."""

    def validate(self, request: GenerationRequest) -> Sequence[str]:
        """Return errors, including reference-image support, without submitting."""

    def submit(self, request: GenerationRequest) -> ProviderJob:
        """Submit one request using runtime credentials and return a normalized job."""

    def status(self, job: ProviderJob) -> ProviderJob:
        """Return the latest normalized state for an existing job."""

    def result(self, job: ProviderJob) -> GeneratedAsset:
        """Return metadata for a successfully finished job."""
