"""Google Veo adapter (Gemini API) — verified REST contract.

API:  POST {base}/models/{model}:predictLongRunning          (header x-goog-api-key)
      GET  {base}/{operation_name}                            (poll until done)
      GET  video.uri + x-goog-api-key (redirects)             (download)
Docs: https://ai.google.dev/gemini-api/docs/veo
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
    negative_prompt_text,
)

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "veo-3.1-generate-preview"

VEO_CAPS = ProviderCapabilities(
    text_to_video=True, image_to_video=True, last_frame=False,
    start_end_frames=False, reference_images=False, audio_generation=True,
    seed_support=False, camera_controls=False,
    local_reference_files=True, cancel_supported=False,
    durations=(4.0, 6.0, 8.0),
    resolutions=("480p", "720p", "1080p"),
    aspect_ratios=("16:9", "9:16"),
    max_reference_slots=1,
    notes=(
        "Gemini API predictLongRunning contract (x-goog-api-key).",
        "Image-to-video uses base64 inline image data (local files OK).",
        "Model configurable via VEO_MODEL (default veo-3.1-generate-preview).",
    ),
)


class VeoAdapter(HttpVideoAdapter):
    key = "veo"
    kind = "video"

    def __init__(self, api_key: str | None, base_url: str | None = None,
                 model: str | None = None, transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(api_key, VEO_CAPS, base_url=base_url or DEFAULT_BASE,
                         transport=transport)
        self.model = model or DEFAULT_MODEL

    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key or "", "Content-Type": "application/json",
                **self.extra_headers}

    # ---------------- translation (PART 5) ----------------
    def translate(self, package: dict, settings: dict) -> dict:
        instances: dict = {"prompt": compose_prompt(package)}
        frame = first_frame_path(package)
        if frame and self.capabilities().image_to_video:
            from .base_http import HttpVideoAdapter as _Base  # noqa: F811
            data_url = _Base._image_as_data_url(frame)
            if data_url:
                mime = data_url[5:data_url.index(";")]
                b64 = data_url[data_url.index(",") + 1:]
                instances["image"] = {"bytesBase64Encoded": b64, "mimeType": mime}
        parameters: dict = {"aspectRatio": settings.get("aspect_ratio") or "16:9"}
        if settings.get("resolution"):
            parameters["resolution"] = settings["resolution"]
        if settings.get("duration_seconds"):
            parameters["durationSeconds"] = int(float(settings["duration_seconds"]))
        negative = negative_prompt_text(package)
        if negative:
            parameters["negativePrompt"] = negative[:900]
        if instances.get("image"):
            parameters["personGeneration"] = "allow_adult"  # required for i2v per docs
        return {"url": f"models/{self.model}:predictLongRunning",
                "body": {"instances": [instances], "parameters": parameters}}

    # ---------------- lifecycle ----------------
    def submit(self, translated: dict) -> ProviderHandle:
        response = self._request("POST", translated["url"], timeout=60.0, json=translated["body"])
        self._check_status(response)
        data = self._json(response)
        name = data.get("name")
        if not name:
            raise ProviderApiError(self.key, response.status_code, "no operation name returned")
        return ProviderHandle(provider_job_id=name, state="submitted", raw=data)

    def poll(self, provider_job_id: str) -> ProviderHandle:
        response = self._request("GET", provider_job_id, timeout=30.0)
        self._check_status(response)
        data = self._json(response)
        if data.get("error"):
            return ProviderHandle(provider_job_id=provider_job_id, state="failed", raw=data)
        if data.get("done"):
            return ProviderHandle(provider_job_id=provider_job_id, state="succeeded", raw=data)
        return ProviderHandle(provider_job_id=provider_job_id, state="generating", raw=data)

    def fetch_result(self, provider_job_id: str) -> ProviderResultInfo:
        handle = self.poll(provider_job_id)
        if handle.state != "succeeded":
            raise ProviderApiError(self.key, 200, f"operation not done yet ({handle.state})")
        data = handle.raw
        response = (data.get("response") or {})
        video_response = response.get("generateVideoResponse") or response
        samples = (video_response.get("generatedSamples")
                   or video_response.get("videos") or [])
        if not samples:
            raise ProviderApiError(self.key, 200, "no generated samples in response")
        video = samples[0].get("video") or samples[0]
        uri = video.get("uri")
        if not uri:
            raise ProviderApiError(self.key, 200, "no video URI in response")
        return ProviderResultInfo(
            download_url=uri,
            mime_type=video.get("mimeType") or "video/mp4",
            usage=response.get("usageMetadata") or {},
            raw=data,
        )

    def validate_connection(self) -> str:
        """Real validation: list models with the credential (free, no generation)."""
        try:
            response = self._request("GET", "models", timeout=30.0)
            if response.status_code in (401, 403):
                return "auth_error"
            if response.status_code >= 400:
                return "api_error"
            return "connected"
        except (ProviderAuthError, ProviderApiError):
            return "api_error"
