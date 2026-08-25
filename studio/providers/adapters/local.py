"""Local / Self-Hosted video adapter — the unlimited-generation lane.

This defines the *Sasquatch Studio Local Video Server contract v1*. It is our
own boundary specification (not a guessed third-party API): any self-hosted
server that implements it can generate for the studio, so the creator is not
dependent on per-generation cloud credits (subject to their own hardware).

Contract (base = LOCAL_VIDEO_API_URL):
  GET  {base}/health            -> 200 {"status": "ok"}        (validation)
  POST {base}/generate          -> 200 {"job_id": "..."}
       body: {
         "prompt": str, "negative_prompt": str,
         "settings": {duration_seconds, resolution, aspect_ratio, seed, generate_audio},
         "first_frame": {"mime_type": str, "data_base64": str} | null,
         "last_frame":  {...} | null,
       }
  GET  {base}/jobs/{job_id}     -> {"status": "queued|running|succeeded|failed",
                                     "progress": 0-100?, "video_url": str?, "error": str?}
  GET  {video_url}              -> video bytes

The provider-neutral generation package is translated into exactly this shape.
Status stays "Not configured" until LOCAL_VIDEO_API_URL is set — local
generation is never pretended to be available.
"""

from __future__ import annotations

import httpx

from ..capabilities import ProviderCapabilities
from ..registry import ProviderApiError
from .base_http import (
    HttpVideoAdapter,
    ProviderHandle,
    ProviderResultInfo,
    compose_prompt,
    first_frame_path,
    last_frame_path,
    negative_prompt_text,
)

LOCAL_CAPS = ProviderCapabilities(
    text_to_video=True, image_to_video=True, last_frame=True,
    start_end_frames=True, reference_images=True, audio_generation=True,
    seed_support=True, camera_controls=True,
    local_reference_files=True, cancel_supported=True,
    durations=(4.0, 5.0, 6.0, 8.0, 10.0),
    resolutions=("480p", "720p", "1080p"),
    aspect_ratios=("16:9", "9:16", "1:1"),
    max_reference_slots=4,
    notes=(
        "Self-hosted lane: same provider-neutral package, no per-video credits "
        "(subject to your hardware). Configure LOCAL_VIDEO_API_URL.",
        "Implements the documented Local Video Server contract v1.",
    ),
)


class LocalVideoAdapter(HttpVideoAdapter):
    key = "local"
    kind = "video"

    def __init__(self, api_url: str, api_key: str | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(api_key or "local", LOCAL_CAPS,
                         base_url=api_url.rstrip("/"), transport=transport)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "local":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ---------------- translation (package -> local contract) ----------------
    def translate(self, package: dict, settings: dict) -> dict:
        body: dict = {
            "prompt": compose_prompt(package),
            "negative_prompt": negative_prompt_text(package),
            "settings": {
                "duration_seconds": settings.get("duration_seconds", 6),
                "resolution": settings.get("resolution", "720p"),
                "aspect_ratio": settings.get("aspect_ratio", "16:9"),
            },
            "first_frame": None,
            "last_frame": None,
        }
        if settings.get("seed") is not None:
            body["settings"]["seed"] = int(settings["seed"])
        if settings.get("generate_audio") is not None:
            body["settings"]["generate_audio"] = bool(settings["generate_audio"])

        def inline(path: str | None) -> dict | None:
            if not path:
                return None
            data_url = self._image_as_data_url(path)
            if not data_url:
                return None
            mime = data_url[5:data_url.index(";")]
            b64 = data_url[data_url.index(",") + 1:]
            return {"mime_type": mime, "data_base64": b64}

        body["first_frame"] = inline(first_frame_path(package))
        body["last_frame"] = inline(last_frame_path(package))
        return {"url": "generate", "body": body}

    # ---------------- lifecycle ----------------
    def submit(self, translated: dict) -> ProviderHandle:
        response = self._request("POST", translated["url"], timeout=60.0, json=translated["body"])
        self._check_status(response)
        data = self._json(response)
        job_id = data.get("job_id")
        if not job_id:
            raise ProviderApiError(self.key, response.status_code, "no job_id returned")
        return ProviderHandle(provider_job_id=str(job_id), state="submitted", raw=data)

    _STATUS_MAP = {"queued": "submitted", "pending": "submitted", "running": "generating",
                   "in_progress": "generating", "succeeded": "succeeded", "done": "succeeded",
                   "failed": "failed", "error": "failed", "cancelled": "failed"}

    def poll(self, provider_job_id: str) -> ProviderHandle:
        response = self._request("GET", f"jobs/{provider_job_id}", timeout=30.0)
        self._check_status(response)
        data = self._json(response)
        state = self._STATUS_MAP.get(str(data.get("status", "")).lower(), "generating")
        return ProviderHandle(provider_job_id=provider_job_id, state=state, raw=data)

    def fetch_result(self, provider_job_id: str) -> ProviderResultInfo:
        handle = self.poll(provider_job_id)
        if handle.state != "succeeded":
            raise ProviderApiError(self.key, 200, f"job not finished ({handle.state})")
        video_url = handle.raw.get("video_url")
        if not video_url:
            raise ProviderApiError(self.key, 200, "no video_url in finished job")
        return ProviderResultInfo(download_url=video_url, mime_type="video/mp4",
                                  usage=handle.raw.get("usage") or {}, raw=handle.raw)

    def cancel(self, provider_job_id: str) -> bool:
        try:
            response = self._request("POST", f"jobs/{provider_job_id}/cancel", timeout=30.0)
            return response.status_code < 400
        except ProviderApiError:
            return False

    def validate_connection(self) -> str:
        try:
            response = self._request("GET", "health", timeout=15.0)
            if response.status_code in (401, 403):
                return "auth_error"
            if response.status_code >= 400:
                return "api_error"
            return "connected"
        except ProviderApiError as error:
            return "api_error" if "timeout" not in str(error) else "temporarily_unavailable"
