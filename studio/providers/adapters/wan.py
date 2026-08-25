"""Wan (Alibaba Model Studio / DashScope, or self-hosted) adapter.

Verified DashScope contract (Model Studio docs):
      POST {base}/services/aigc/video-generation/video-synthesis
           headers: Authorization: Bearer …, X-DashScope-Async: enable
      GET  {base}/tasks/{task_id}         (PENDING/RUNNING/SUCCEEDED/FAILED)
      result: output.video_url

Configuration:
  WAN_API_KEY + WAN_API_BASE_URL (or DASHSCOPE_API_KEY) for hosted;
  a custom base URL supports self-hosted DashScope-compatible endpoints.
Docs: https://www.alibabacloud.com/help/en/model-studio/
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

DEFAULT_BASES = {
    "beijing": "https://dashscope.aliyuncs.com/api/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/api/v1",
    "virginia": "https://dashscope-us.aliyuncs.com/api/v1",
}
DEFAULT_REGION = "singapore"
DEFAULT_T2V_MODEL = "wan2.2-t2v-plus"
DEFAULT_I2V_MODEL = "wan2.2-i2v-plus"

WAN_CAPS = ProviderCapabilities(
    text_to_video=True, image_to_video=True, last_frame=False,
    start_end_frames=False, reference_images=False, audio_generation=False,
    seed_support=False, camera_controls=False,
    url_reference_only=True, cancel_supported=False,
    durations=(5.0,),
    resolutions=("480P", "720P", "1080P"),
    aspect_ratios=("16:9", "9:16", "1:1"),
    max_reference_slots=1,
    notes=(
        "DashScope async video-synthesis contract (X-DashScope-Async).",
        "Hosted (WAN_API_KEY/DASHSCOPE_API_KEY) or self-hosted endpoint (WAN_API_BASE_URL).",
        "Models configurable via WAN_T2V_MODEL / WAN_I2V_MODEL.",
    ),
)


class WanAdapter(HttpVideoAdapter):
    key = "wan"
    kind = "video"

    def __init__(self, api_key: str | None, base_url: str | None = None,
                 region: str | None = None, t2v_model: str | None = None,
                 i2v_model: str | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(api_key, WAN_CAPS, transport=transport)
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = DEFAULT_BASES.get(region or DEFAULT_REGION,
                                             DEFAULT_BASES[DEFAULT_REGION]).rstrip("/")
        self.t2v_model = t2v_model or DEFAULT_T2V_MODEL
        self.i2v_model = i2v_model or DEFAULT_I2V_MODEL

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key or ''}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable", **self.extra_headers}

    def _http_headers(self) -> dict:
        # task polling must NOT send X-DashScope-Async
        headers = dict(self._headers())
        headers.pop("X-DashScope-Async", None)
        return headers

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=timeout,
                            transport=self._transport, headers=self._http_headers())

    # ---------------- translation ----------------
    def translate(self, package: dict, settings: dict) -> dict:
        frames = package.get("frame_references") or {}

        def external_url(purpose: str) -> str | None:
            for entry in frames.get(purpose) or []:
                path = entry.get("path") or ""
                if path.startswith(("http://", "https://")):
                    return path
            return None

        first = external_url("first_frame") or external_url("prev_shot_frame")
        input_body: dict = {"prompt": compose_prompt(package)}
        negative = negative_prompt_text(package)
        if negative:
            input_body["negative_prompt"] = negative[:500]
        if first and self.capabilities().image_to_video:
            input_body["img_url"] = first
        model = self.i2v_model if first else self.t2v_model
        parameters: dict = {}
        if settings.get("resolution"):
            parameters["resolution"] = str(settings["resolution"])
        if settings.get("aspect_ratio"):
            parameters["ratio"] = settings["aspect_ratio"]
        body = {"model": model, "input": input_body, "parameters": parameters}
        return {"url": "services/aigc/video-generation/video-synthesis", "body": body}

    # ---------------- lifecycle ----------------
    def submit(self, translated: dict) -> ProviderHandle:
        response = self._request("POST", translated["url"], timeout=60.0, json=translated["body"])
        self._check_status(response)
        data = self._json(response)
        task_id = (data.get("output") or {}).get("task_id")
        if not task_id:
            raise ProviderApiError(self.key, response.status_code, "no task_id returned")
        return ProviderHandle(provider_job_id=task_id, state="submitted", raw=data)

    _STATUS_MAP = {"PENDING": "submitted", "RUNNING": "generating",
                   "SUCCEEDED": "succeeded", "FAILED": "failed",
                   "CANCELED": "failed", "UNKNOWN": "generating"}

    def poll(self, provider_job_id: str) -> ProviderHandle:
        response = self._request("GET", f"tasks/{provider_job_id}", timeout=30.0)
        self._check_status(response)
        data = self._json(response)
        output = data.get("output") or {}
        status = str(output.get("task_status", "")).upper()
        state = self._STATUS_MAP.get(status, "generating")
        return ProviderHandle(provider_job_id=provider_job_id, state=state, raw=data)

    def fetch_result(self, provider_job_id: str) -> ProviderResultInfo:
        handle = self.poll(provider_job_id)
        if handle.state != "succeeded":
            raise ProviderApiError(self.key, 200, f"task not finished ({handle.state})")
        output = handle.raw.get("output") or {}
        video_url = output.get("video_url")
        if not video_url:
            raise ProviderApiError(self.key, 200, "no video_url in finished task")
        return ProviderResultInfo(download_url=video_url, mime_type="video/mp4",
                                  usage=data_usage(handle.raw), raw=handle.raw)

    def validate_connection(self) -> str:
        """Real validation without generating: GET a task with a sentinel id."""
        try:
            response = self._request("GET", "tasks/studio-connection-check", timeout=30.0)
            if response.status_code in (401, 403):
                return "auth_error"
            if response.status_code >= 500:
                return "api_error"
            # 404 / invalid-task-id responses still prove authentication passed
            return "connected"
        except ProviderAuthError:
            return "auth_error"
        except ProviderApiError:
            return "api_error"


def data_usage(raw: dict) -> dict:
    return raw.get("usage") or {}
