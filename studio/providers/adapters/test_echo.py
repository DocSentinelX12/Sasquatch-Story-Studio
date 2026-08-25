"""TEST adapter — clearly marked, disabled by default (PART 22).

Enabled ONLY when STUDIO_TEST_PROVIDER=1 (server-side). It performs no network
calls and never contacts a paid API. Its "results" are local marker files that
are ALWAYS labelled as test output — never presented as real AI generation.
Use it to exercise the queue, review and versioning workflows in development.
"""

from __future__ import annotations

import itertools
import time

from ..capabilities import ProviderCapabilities
from .base_http import HttpVideoAdapter, ProviderHandle, ProviderResultInfo

TEST_CAPS = ProviderCapabilities(
    text_to_video=True, image_to_video=True, last_frame=True,
    start_end_frames=True, reference_images=True, audio_generation=False,
    seed_support=True, camera_controls=True,
    local_reference_files=True, cancel_supported=True,
    durations=(1.0, 2.0, 3.0),
    resolutions=("480p", "720p"),
    aspect_ratios=("16:9", "9:16"),
    max_reference_slots=8,
    notes=("TEST ADAPTER — not a real provider. Enable with STUDIO_TEST_PROVIDER=1.",),
)

_counter = itertools.count(1)


def _clip(body) -> dict:
    """Keep translated request previews small for storage."""
    import json
    try:
        text = json.dumps(body, default=str)
        if len(text) > 4000:
            return {"truncated": True, "preview": text[:4000]}
        return body
    except (TypeError, ValueError):
        return {"unserializable": True}


class TestEchoAdapter(HttpVideoAdapter):
    key = "test-echo"
    kind = "video"
    is_test = True

    def __init__(self, transport=None) -> None:
        super().__init__("test-key", TEST_CAPS, base_url="test://local", transport=transport)

    def _headers(self) -> dict:
        return {}

    def capabilities(self) -> ProviderCapabilities:
        return TEST_CAPS

    def translate(self, package: dict, settings: dict) -> dict:
        # echoes the universal package back — translation is a passthrough
        return {"url": "test://echo", "body": {"package_summary": {
            "characters": [c.get("name") for c in package.get("characters", [])],
            "camera": package.get("camera"),
            "duration": settings.get("duration_seconds", 2),
        }, "settings": settings,
            "test_marker": "TEST ADAPTER REQUEST — no provider was contacted"}}

    def submit(self, translated: dict) -> ProviderHandle:
        # stateless by design: the id encodes submit time + failure intent so
        # any adapter instance (e.g. the poll worker's) can poll it.
        body = translated.get("body") or {}
        fail = bool((body.get("settings") or {}).get("test_force_failure"))
        job_id = f"test-{next(_counter):06d}-{int(time.time())}{'-fail' if fail else ''}"
        return ProviderHandle(provider_job_id=job_id, state="submitted",
                              raw={"test": True, "request": _clip(translated["body"])})

    def poll(self, provider_job_id: str) -> ProviderHandle:
        parts = provider_job_id.rsplit("-", 2)
        try:
            submitted_at = float(parts[-2])
        except (ValueError, IndexError):
            submitted_at = time.time() - 10.0
        forced_fail = provider_job_id.endswith("-fail")
        if forced_fail:
            return ProviderHandle(provider_job_id=provider_job_id, state="failed",
                                  raw={"test": True, "error": "test-forced-failure"})
        elapsed = time.time() - submitted_at
        # succeed ~2s after submit so tests exercise the generating state
        state = "generating" if elapsed < 2.0 else "succeeded"
        return ProviderHandle(provider_job_id=provider_job_id, state=state,
                              raw={"test": True, "elapsed": round(elapsed, 2)})

    def fetch_result(self, provider_job_id: str) -> ProviderResultInfo:
        return ProviderResultInfo(
            download_url=f"test-echo://local/{provider_job_id}",
            mime_type="video/mp4",
            usage={"test_adapter": True},
            raw={"test": True, "provider": "test-echo"},
        )

    def cancel(self, provider_job_id: str) -> bool:
        return True

    def validate_connection(self) -> str:
        return "connected"
