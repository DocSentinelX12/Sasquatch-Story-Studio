"""Shared HTTP video-adapter base (Phase 5).

Implements the provider contract against verified REST APIs using a sync httpx
client (adapters run inside background worker threads). The universal
generation package is translated here; it is never changed to suit a provider.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

import httpx

from ..capabilities import ProviderCapabilities
from ..registry import ProviderApiError, ProviderAuthError

TIMEOUT_SUBMIT = 60.0
TIMEOUT_POLL = 30.0
TIMEOUT_DOWNLOAD = 300.0


@dataclass(frozen=True)
class ProviderHandle:
    """Normalized handle for one submitted generation."""
    provider_job_id: str
    state: str                      # submitted | generating | succeeded | failed
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResultInfo:
    """Normalized result metadata for one finished generation."""
    download_url: str | None
    mime_type: str | None
    usage: dict
    raw: dict = field(default_factory=dict)


class VideoAdapter(Protocol):
    """Phase 5 adapter contract (extends the Phase 1 GenerationProvider)."""

    key: str

    def capabilities(self) -> ProviderCapabilities: ...
    def translate(self, package: dict, settings: dict) -> dict: ...
    def submit(self, translated: dict) -> ProviderHandle: ...
    def poll(self, provider_job_id: str) -> ProviderHandle: ...
    def fetch_result(self, provider_job_id: str) -> ProviderResultInfo: ...
    def cancel(self, provider_job_id: str) -> bool: ...
    def validate_connection(self) -> str: ...   # connected | auth_error | api_error


class HttpVideoAdapter:
    """Base class implementing shared HTTP + error handling."""

    key = "base"
    base_url = ""
    kind = "video"

    def __init__(self, api_key: str | None, caps: ProviderCapabilities,
                 base_url: str | None = None, extra_headers: dict | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self.caps_obj = caps
        self.base_url = base_url or self.base_url
        self.extra_headers = extra_headers or {}
        self._transport = transport   # test injection only

    def capabilities(self) -> ProviderCapabilities:
        return self.caps_obj

    # ---------------- helpers ----------------
    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=self._transport,   # None -> real network transport
            headers=self._headers(),
        )

    def _headers(self) -> dict:
        raise NotImplementedError

    def _request(self, method: str, url: str, *, timeout: float, **kwargs) -> httpx.Response:
        try:
            with self._client(timeout) as client:
                return client.request(method, url, **kwargs)
        except httpx.TimeoutException as error:
            raise ProviderApiError(self.key, 0, f"timeout: {error}") from error
        except httpx.HTTPError as error:
            raise ProviderApiError(self.key, 0, str(error)) from error

    def _check_status(self, response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise ProviderAuthError(self.key, f"HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ProviderApiError(self.key, response.status_code, response.text[:300])

    def _json(self, response: httpx.Response) -> dict:
        try:
            return response.json()
        except ValueError as error:
            raise ProviderApiError(self.key, response.status_code, "invalid JSON response") from error

    @staticmethod
    def _image_as_data_url(path: str) -> str | None:
        """Local file -> data URL (only for providers accepting inline bytes)."""
        try:
            file_path = Path(path)
            if not file_path.is_file():
                return None
            mime = "image/png" if file_path.suffix.lower() == ".png" else "image/jpeg"
            data = base64.b64encode(file_path.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{data}"
        except OSError:
            return None

    # ---------------- contract defaults ----------------
    def translate(self, package: dict, settings: dict) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def submit(self, translated: dict) -> ProviderHandle:  # pragma: no cover - abstract
        raise NotImplementedError

    def poll(self, provider_job_id: str) -> ProviderHandle:  # pragma: no cover - abstract
        raise NotImplementedError

    def fetch_result(self, provider_job_id: str) -> ProviderResultInfo:  # pragma: no cover
        raise NotImplementedError

    def cancel(self, provider_job_id: str) -> bool:
        """Default: cancellation unsupported (honest per-provider reporting)."""
        return False

    def download(self, url: str, headers: dict | None = None) -> bytes:
        try:
            with httpx.Client(timeout=TIMEOUT_DOWNLOAD, follow_redirects=True,
                              transport=self._transport) as client:
                response = client.get(url, headers={**self._headers(), **(headers or {})})
                self._check_status(response)
                return response.content
        except httpx.TimeoutException as error:
            raise ProviderApiError(self.key, 0, f"download timeout: {error}") from error
        except httpx.HTTPError as error:
            raise ProviderApiError(self.key, 0, f"download failed: {error}") from error

    def validate_connection(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError


# Prompt assembly shared by adapters: universal package -> text prompt
def compose_prompt(package: dict) -> str:
    """Build the provider text prompt from the universal package (PART 5)."""
    parts: list[str] = []
    style = package.get("visual_style")
    if isinstance(style, list):
        parts.append(f"Visual style: {', '.join(str(s) for s in style)}.")
    elif style:
        parts.append(f"Visual style: {style}.")
    camera = package.get("camera") or {}
    camera_bits = [camera.get("shot_type"), camera.get("angle"), camera.get("movement"),
                   camera.get("notes"), camera.get("lens_framing")]
    camera_bits = [str(b) for b in camera_bits if b]
    if camera_bits:
        parts.append(f"Camera: {', '.join(camera_bits)}.")
    composition = package.get("composition") or {}
    comp_bits = [composition.get("description"), composition.get("subject_position")]
    comp_bits = [str(b) for b in comp_bits if b]
    if comp_bits:
        parts.append(f"Composition: {'; '.join(comp_bits)}.")
    characters = package.get("characters") or []
    for character in characters:
        bits = [character.get("standard_appearance"), character.get("outfit"),
                character.get("species") and f"species: {character['species']}"]
        bits = [str(b) for b in bits if b]
        if bits:
            parts.append(f"Character {character.get('name')}: {'; '.join(bits)}.")
        for rule in character.get("visual_rules") or []:
            parts.append(f"{character.get('name')} visual rule: {rule}")
        for rule in character.get("never_changes") or []:
            parts.append(f"{character.get('name')} must not change: {rule}")
        action = character.get("action_note") or character.get("role_in_shot")
        if action:
            parts.append(f"{character.get('name')} in this shot: {action}.")
    location = package.get("location") or {}
    if location.get("name"):
        loc_bits = [location.get("description"), location.get("environment")]
        loc_bits = [str(b) for b in loc_bits if b]
        parts.append(f"Location {location['name']}: {'; '.join(loc_bits)}.")
        for rule in location.get("visual_rules") or []:
            parts.append(f"Location rule: {rule}")
    props = package.get("props") or []
    if props:
        parts.append("Props: " + ", ".join(str(p.get("name")) for p in props) + ".")
    action_block = package.get("action") or {}
    action_bits = [action_block.get("description"), action_block.get("general"),
                   action_block.get("character_action"), action_block.get("facial_expression"),
                   action_block.get("environment_action") or package.get("environment_movement")]
    action_bits = [str(b) for b in action_bits if b]
    if action_bits:
        parts.append("Action: " + "; ".join(action_bits) + ".")
    if package.get("lighting"):
        parts.append(f"Lighting: {package['lighting']}.")
    if package.get("weather"):
        parts.append(f"Weather: {package['weather']}.")
    timing = package.get("dialogue_timing") or {}
    lines = timing.get("shot_dialogue") or []
    for line in lines[:8]:
        parts.append(f"Lip-sync line: {line}")
    if timing.get("shot_narration"):
        parts.append(f"Narration (voice-over): {timing['shot_narration']}")
    continuity = package.get("continuity_requirements") or {}
    if continuity.get("barefoot_rule"):
        parts.append(f"ABSOLUTE RULE: {continuity['barefoot_rule']}")
    if continuity.get("shot_notes"):
        parts.append(f"Continuity: {continuity['shot_notes']}")
    negative = package.get("negative_constraints") or []
    if negative:
        parts.append("Avoid: " + "; ".join(str(n) for n in negative[:10]) + ".")
    return "\n".join(parts)


def negative_prompt_text(package: dict) -> str:
    return "; ".join(str(n) for n in (package.get("negative_constraints") or [])[:15])


def first_frame_path(package: dict) -> str | None:
    frames = package.get("frame_references") or {}
    for purpose in ("first_frame", "prev_shot_frame", "keyframe"):
        entries = frames.get(purpose) or []
        if entries and entries[0].get("path"):
            return entries[0]["path"]
    return None


def last_frame_path(package: dict) -> str | None:
    frames = package.get("frame_references") or {}
    for purpose in ("last_frame", "next_shot_frame"):
        entries = frames.get(purpose) or []
        if entries and entries[0].get("path"):
            return entries[0]["path"]
    return None
