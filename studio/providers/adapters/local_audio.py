"""Local / Self-Hosted AUDIO adapter — the free-lane TTS boundary.

Defines the *Sasquatch Studio Local Audio Server contract v1* (our own
boundary, not a guessed third-party API). Any local TTS / voice-clone /
narration server implementing it works without studio changes — no per-
generation cloud credits (subject to your hardware).

Contract (base = LOCAL_AUDIO_API_URL):
  GET  {base}/health                      -> 200 {"status": "ok"}
  POST {base}/tts                         -> 200 {"job_id": "..."}  (async)
       body: {text, voice_id?, style?, speed?, pitch?, emotion?,
              format: "wav"|"mp3", sample_rate?}
  GET  {base}/jobs/{job_id}               -> {"status": "queued|running|succeeded|failed",
                                               "audio_url"?, "duration_seconds"?, "error"?}
  GET  {audio_url}                        -> audio bytes

Status stays "Not configured" until LOCAL_AUDIO_API_URL is set. Nothing is
fabricated. Cloud audio boundaries (unverified contracts) refuse honestly.
"""

from __future__ import annotations

import httpx

from ..capabilities import ProviderCapabilities
from ..registry import ProviderApiError
from .base_http import HttpVideoAdapter, ProviderHandle, ProviderResultInfo

AUDIO_CAPS = ProviderCapabilities(
    audio_generation=True, text_to_video=False,
    durations=(), resolutions=(), aspect_ratios=(),
    notes=(
        "Self-hosted TTS/narration lane. Configure LOCAL_AUDIO_API_URL.",
        "Implements the Local Audio Server contract v1 (/health, /tts, /jobs/{id}).",
    ),
)


class LocalAudioAdapter(HttpVideoAdapter):
    key = "local-audio"
    kind = "audio"

    def __init__(self, api_url: str, api_key: str | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        super().__init__(api_key or "local", AUDIO_CAPS,
                         base_url=api_url.rstrip("/"), transport=transport)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "local":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def translate(self, package: dict, settings: dict) -> dict:
        """package for audio = {text, voice_profile, timing}; provider-neutral."""
        voice = package.get("voice_profile") or {}
        body = {
            "text": package.get("text", ""),
            "voice_id": voice.get("voice_id"),
            "style": voice.get("voice_style"),
            "speed": voice.get("speaking_speed", 1.0),
            "emotion": voice.get("emotion_notes"),
            "format": settings.get("format", "wav"),
        }
        if voice.get("pitch") is not None:
            body["pitch"] = voice["pitch"]
        return {"url": "tts", "body": body}

    def submit(self, translated: dict) -> ProviderHandle:
        response = self._request("POST", translated["url"], timeout=60.0, json=translated["body"])
        self._check_status(response)
        data = self._json(response)
        job_id = data.get("job_id")
        if not job_id:
            raise ProviderApiError(self.key, response.status_code, "no job_id returned")
        return ProviderHandle(provider_job_id=str(job_id), state="submitted", raw=data)

    _STATUS_MAP = {"queued": "submitted", "pending": "submitted", "running": "generating",
                   "succeeded": "succeeded", "failed": "failed"}

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
        audio_url = handle.raw.get("audio_url")
        if not audio_url:
            raise ProviderApiError(self.key, 200, "no audio_url in finished job")
        return ProviderResultInfo(download_url=audio_url,
                                  mime_type="audio/wav",
                                  usage={"duration_seconds": handle.raw.get("duration_seconds")},
                                  raw=handle.raw)

    def validate_connection(self) -> str:
        try:
            response = self._request("GET", "health", timeout=15.0)
            if response.status_code in (401, 403):
                return "auth_error"
            if response.status_code >= 400:
                return "api_error"
            return "connected"
        except ProviderApiError:
            return "api_error"


class TestEchoAudioAdapter(LocalAudioAdapter):
    """Clearly-marked TEST audio adapter (no network). Produces a small,
    genuinely-valid silent WAV file labelled as TEST output — never presented
    as real AI speech. Enabled only with STUDIO_TEST_PROVIDER=1."""

    key = "test-echo-audio"
    kind = "audio"
    is_test = True

    def __init__(self, transport=None) -> None:
        super().__init__("test://local", transport=transport)
        self._jobs: dict[str, dict] = {}

    def submit(self, translated: dict) -> ProviderHandle:
        import time
        job_id = f"taudio-{int(time.time() * 1000)}"
        self._jobs[job_id] = {"at": time.time(), "request": translated["body"],
                              "fail": bool(translated["body"].get("test_force_failure"))}
        return ProviderHandle(provider_job_id=job_id, state="submitted", raw={"test": True})

    def poll(self, provider_job_id: str) -> ProviderHandle:
        import time
        config = self._jobs.get(provider_job_id, {"at": time.time() - 10, "fail": False})
        if config.get("fail"):
            return ProviderHandle(provider_job_id=provider_job_id, state="failed",
                                  raw={"test": True, "error": "test-forced-failure"})
        elapsed = time.time() - config.get("at", 0)
        state = "generating" if elapsed < 1.5 else "succeeded"
        return ProviderHandle(provider_job_id=provider_job_id, state=state, raw={"test": True})

    def fetch_result(self, provider_job_id: str) -> ProviderResultInfo:
        request = self._jobs.get(provider_job_id, {}).get("request", {})
        duration = max(0.8, len(request.get("text", "")) / 16.0)  # rough speech estimate
        return ProviderResultInfo(
            download_url=f"test-audio://local/{provider_job_id}",
            mime_type="audio/wav", usage={"duration_seconds": round(duration, 2),
                                          "test_adapter": True},
            raw={"test": True, "provider": "test-echo-audio"})

    def validate_connection(self) -> str:
        return "connected"

    def download(self, url: str, headers=None) -> bytes:
        """Real, valid WAV (label lives in metadata, never presented as speech)."""
        job_id = url.rsplit("/", 1)[-1]
        request = self._jobs.get(job_id, {}).get("request", {})
        duration = max(0.8, len(request.get("text", "")) / 16.0)
        return silent_wav(duration)


def silent_wav(duration_seconds: float, sample_rate: int = 8000) -> bytes:
    """Minimal valid WAV: 8-bit mono, soft 440Hz blip for 0.15s then silence."""
    import io
    import math
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(sample_rate)
        frames = int(duration_seconds * sample_rate)
        chunk = bytearray()
        for i in range(frames):
            if i < sample_rate * 0.15:
                chunk.append(int(128 + 60 * math.sin(2 * math.pi * 440 * i / sample_rate)))
            else:
                chunk.append(128)
        wav_file.writeframes(bytes(chunk))
    return buffer.getvalue()
