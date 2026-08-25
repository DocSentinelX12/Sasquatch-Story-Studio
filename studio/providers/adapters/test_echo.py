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


class TestEchoAdapter(HttpVideoAdapter):
    key = "test-echo"
    kind = "video"
    is_test = True

    def __init__(self, transport=None) -> None:
        super().__init__("test-key", TEST_CAPS, base_url="test://local", transport=transport)
        self.submitted_at: dict[str, float] = {}
        self.behavior: dict[str, dict] = {}   # job_id -> {"fail": bool, "succeed_after_polls": n}

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
        job_id = f"test-{next(_counter):06d}-{int(time.time())}"
        self.submitted_at[job_id] = time.time()
        self.behavior[job_id] = {
            "fail": bool((translated.get("settings") or {}).get("test_force_failure")),
        }
        return ProviderHandle(provider_job_id=job_id, state="submitted",
                              raw={"test": True, "request": translated["body"]})

    def poll(self, provider_job_id: str) -> ProviderHandle:
        config = self.behavior.get(provider_job_id, {})
        elapsed = time.time() - self.submitted_at.get(provider_job_id, time.time())
        if config.get("fail"):
            return ProviderHandle(provider_job_id=provider_job_id, state="failed",
                                  raw={"test": True, "error": "test-forced-failure"})
        # succeed ~2s after submit so tests exercise the generating state
        state = "generating" if elapsed < 2.0 else "succeeded"
        return ProviderHandle(provider_job_id=provider_job_id, state=state,
                              raw={"test": True, "elapsed": elapsed})

    def fetch_result(self, provider_job_id: str) -> ProviderResultInfo:
        return ProviderResultInfo(
            download_url=f"test-echo://local/{provider_job_id}",
            mime_type="video/mp4",
            usage={"test_adapter": True},
            raw={"test": True, "provider": "test-echo"},
        )

    def cancel(self, provider_job_id: str) -> bool:
        self.behavior[provider_job_id] = {"fail": True}
        return True

    def validate_connection(self) -> str:
        return "connected"
