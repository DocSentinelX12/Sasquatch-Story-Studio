"""Seedance (Volcano Engine Ark) adapter — verified REST contract.

API:  POST {base}/contents/generations/tasks        (Authorization: Bearer)
      GET  {base}/contents/generations/tasks/{id}   (poll: queued/running/succeeded)
      result: content.video_url
Docs: https://www.volcengine.com/docs/85621
"""

from __future__ import annotations

import httpx

from ..capabilities import ProviderCapabilities
from ..registry import ProviderApiError, ProviderAuthError
from .base_http import (
    HttpVideoAdapter,
    ProviderHandle,
    ProviderResultInfo,
    compose_prompt,
    first_frame_path,
    last_frame_path,
    negative_prompt_text,
)

DEFAULT_BASE = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seedance-2-0-260128"

SEEDANCE_CAPS = ProviderCapabilities(
    text_to_video=True, image_to_video=True, last_frame=True,
    start_end_frames=True, reference_images=False, audio_generation=True,
    seed_support=True, camera_controls=True,
    url_reference_only=True, cancel_supported=False,
    durations=(4.0, 5.0, 8.0, 10.0),
    resolutions=("480p", "720p", "1080p"),
    aspect_ratios=("16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"),
    max_reference_slots=2,
    notes=(
        "Volcano Engine Ark contents/generations/tasks contract.",
        "Reference images must be publicly accessible URLs (no local-file upload).",
        "Model configurable via SEEDANCE_MODEL.",
    ),
)


class SeedanceAdapter(HttpVideoAdapter):
    key = "seedance"
    kind = "video"

    def __init__(self, api_key: str | None, base_url: str | None = None,
                 model: str | None = None, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(api_key, SEEDANCE_CAPS, base_url=base_url or DEFAULT_BASE,
                         transport=transport)
        self.model = model or DEFAULT_MODEL

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key or ''}",
                "Content-Type": "application/json", **self.extra_headers}

    # ---------------- translation ----------------
    def translate(self, package: dict, settings: dict) -> dict:
        content: list[dict] = [{"type": "text", "text": compose_prompt(package)}]
        frames = package.get("frame_references") or {}

        def external_url(purpose: str) -> str | None:
            for entry in frames.get(purpose) or []:
                path = entry.get("path") or ""
                if path.startswith(("http://", "https://")):
                    return path
            return None

        first = external_url("first_frame") or external_url("prev_shot_frame")
        if first and self.capabilities().image_to_video:
            content.append({"type": "image_url", "image_url": {"url": first},
                            "role": "first_frame"})
        last = external_url("last_frame") or external_url("next_shot_frame")
        if last and self.capabilities().last_frame:
            content.append({"type": "image_url", "image_url": {"url": last},
                            "role": "last_frame"})
        body: dict = {"model": self.model, "content": content}
        if settings.get("aspect_ratio"):
            body["ratio"] = settings["aspect_ratio"]
        if settings.get("duration_seconds"):
            body["duration"] = int(float(settings["duration_seconds"]))
        if settings.get("resolution"):
            body["resolution"] = str(settings["resolution"]).lower()
        if settings.get("generate_audio") is not None:
            body["generate_audio"] = bool(settings.get("generate_audio"))
        if settings.get("seed") is not None and self.capabilities().seed_support:
            body["seed"] = int(settings["seed"])
        negative = negative_prompt_text(package)
        if negative:
            body.setdefault("extra", {})["negative_prompt"] = negative[:500]
        body["watermark"] = False
        return {"url": "contents/generations/tasks", "body": body}

    # ---------------- lifecycle ----------------
    def submit(self, translated: dict) -> ProviderHandle:
        response = self._request("POST", translated["url"], timeout=60.0, json=translated["body"])
        self._check_status(response)
        data = self._json(response)
        task_id = data.get("id")
        if not task_id:
            raise ProviderApiError(self.key, response.status_code, "no task id returned")
        return ProviderHandle(provider_job_id=task_id, state="submitted", raw=data)

    _STATUS_MAP = {"queued": "submitted", "running": "generating",
                   "succeeded": "succeeded", "failed": "failed",
                   "cancelled": "failed"}

    def poll(self, provider_job_id: str) -> ProviderHandle:
        response = self._request("GET", f"contents/generations/tasks/{provider_job_id}", timeout=30.0)
        self._check_status(response)
        data = self._json(response)
        state = self._STATUS_MAP.get(str(data.get("status", "")).lower(), "generating")
        return ProviderHandle(provider_job_id=provider_job_id, state=state, raw=data)

    def fetch_result(self, provider_job_id: str) -> ProviderResultInfo:
        handle = self.poll(provider_job_id)
        if handle.state != "succeeded":
            raise ProviderApiError(self.key, 200, f"task not finished ({handle.state})")
        data = handle.raw
        video_url = ((data.get("content") or {}).get("video_url")
                     or (data.get("output") or {}).get("video_url"))
        if not video_url:
            raise ProviderApiError(self.key, 200, "no video_url in finished task")
        return ProviderResultInfo(download_url=video_url, mime_type="video/mp4",
                                  usage=data.get("usage") or {}, raw=data)

    def validate_connection(self) -> str:
        """Real validation without generating: GET a task with a sentinel id.
        401/403 -> auth error; 404 means credentials are valid (task lookup worked)."""
        try:
            response = self._request("GET", "contents/generations/tasks/studio-connection-check",
                                     timeout=30.0)
            if response.status_code in (401, 403):
                return "auth_error"
            if response.status_code == 404:
                return "connected"
            if response.status_code >= 400:
                return "api_error"
            return "connected"
        except ProviderAuthError:
            return "auth_error"
        except ProviderApiError:
            return "api_error"
