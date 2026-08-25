"""Honest provider adapter stubs.

Each module below follows the `GenerationProvider` protocol from
studio/providers/base.py, but no external API is called in Phase 1. The stubs
exist so the rest of the application can be built against the real interface
and fail with clear, truthful errors instead of fake successes.

When integrating a real provider:
1. Implement `submit`, `status`, `result` in the provider's module.
2. Keep credentials server-side only (read them here, never return them).
3. Never mark a result approved — approval is the creator's decision.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..base import GenerationRequest, ProviderJob
from ..registry import AdapterNotImplemented, ProviderNotConfigured, get_definition


class StubVideoAdapter:
    """Shared behavior for video adapters that are not yet connected."""

    def __init__(self, key: str) -> None:
        self._key = key
        definition = get_definition(key)
        if definition is None:
            raise ValueError(f"Unknown provider key: {key}")
        self._definition = definition

    @property
    def name(self) -> str:
        return self._key

    def _fail_if_unusable(self) -> None:
        missing = self._definition.missing_env()
        if missing:
            raise ProviderNotConfigured(self._key, missing)
        raise AdapterNotImplemented(self._key)

    def validate(self, request: GenerationRequest) -> Sequence[str]:
        """Static checks only — no network access, no credential use."""
        from ..base import validate_reference_images

        errors: list[str] = list(validate_reference_images(request))
        if request.media_kind.value not in ("video", "animation_test"):
            errors.append(f"{self._key} only accepts video media kinds")
        return errors

    def submit(self, request: GenerationRequest) -> ProviderJob:
        self._fail_if_unusable()  # pragma: no cover - always raises in Phase 1
        raise AssertionError("unreachable in Phase 1")

    def status(self, job: ProviderJob) -> ProviderJob:
        self._fail_if_unusable()  # pragma: no cover
        raise AssertionError("unreachable in Phase 1")

    def result(self, job: ProviderJob) -> Any:
        self._fail_if_unusable()  # pragma: no cover
        raise AssertionError("unreachable in Phase 1")


class SeedanceAdapter(StubVideoAdapter):
    """Seedance — not connected. See studio/providers/adapters/__init__.py."""


class VeoAdapter(StubVideoAdapter):
    """Google Veo — not connected. See studio/providers/adapters/__init__.py."""


class WanAdapter(StubVideoAdapter):
    """Wan — not connected. See studio/providers/adapters/__init__.py."""


ADAPTERS: dict[str, StubVideoAdapter] = {
    "seedance": SeedanceAdapter("seedance"),
    "veo": VeoAdapter("veo"),
    "wan": WanAdapter("wan"),
}


def get_adapter(key: str) -> StubVideoAdapter | None:
    return ADAPTERS.get(key)
