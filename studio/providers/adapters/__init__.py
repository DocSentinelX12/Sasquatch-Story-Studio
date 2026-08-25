"""Provider adapter registry.

Real adapters ship here in Phase 5 (veo / seedance / wan) plus an explicitly
marked TEST adapter that is disabled unless STUDIO_TEST_PROVIDER=1. Adapters
are constructed lazily from server-side credentials only.
"""

from __future__ import annotations

from typing import Optional

from ...config import env
from ..registry import DEFINITIONS, ProviderNotConfigured
from .base_http import HttpVideoAdapter, ProviderHandle, ProviderResultInfo
from .seedance import SeedanceAdapter
from .veo import VeoAdapter
from .wan import WanAdapter

__all__ = [
    "HttpVideoAdapter", "ProviderHandle", "ProviderResultInfo",
    "get_video_adapter", "SeedanceAdapter", "VeoAdapter", "WanAdapter",
]


def _env(name: str) -> Optional[str]:
    value = env(name)
    return value or None


def get_video_adapter(key: str, transport=None):
    """Build the adapter for a provider key from server-side credentials.

    Raises ProviderNotConfigured when required credentials are missing.
    `transport` is for automated tests only (httpx.MockTransport).
    """
    if key == "veo":
        api_key = _env("GEMINI_API_KEY")
        if not api_key:
            raise ProviderNotConfigured("veo", ["GEMINI_API_KEY"])
        return VeoAdapter(api_key, base_url=_env("VEO_API_BASE_URL"),
                          model=_env("VEO_MODEL"), transport=transport)
    if key == "seedance":
        api_key = _env("SEEDANCE_API_KEY")
        if not api_key:
            raise ProviderNotConfigured("seedance", ["SEEDANCE_API_KEY"])
        return SeedanceAdapter(api_key, base_url=_env("SEEDANCE_API_BASE_URL"),
                               model=_env("SEEDANCE_MODEL"), transport=transport)
    if key == "wan":
        api_key = _env("WAN_API_KEY") or _env("DASHSCOPE_API_KEY")
        required = ["WAN_API_KEY", "DASHSCOPE_API_KEY"]
        if not api_key:
            raise ProviderNotConfigured("wan", required)
        return WanAdapter(api_key, base_url=_env("WAN_API_BASE_URL"),
                          region=_env("WAN_REGION"),
                          t2v_model=_env("WAN_T2V_MODEL"), i2v_model=_env("WAN_I2V_MODEL"),
                          transport=transport)
    if key == "local-audio":
        api_url = _env("LOCAL_AUDIO_API_URL")
        if not api_url:
            raise ProviderNotConfigured("local-audio", ["LOCAL_AUDIO_API_URL"])
        from .local_audio import LocalAudioAdapter
        return LocalAudioAdapter(api_url, api_key=_env("LOCAL_AUDIO_API_KEY"), transport=transport)
    if key == "test-echo-audio":
        if (env("STUDIO_TEST_PROVIDER") or "").lower() not in ("1", "true", "yes"):
            raise ProviderNotConfigured("test-echo-audio", ["STUDIO_TEST_PROVIDER=1"])
        from .local_audio import TestEchoAudioAdapter
        return TestEchoAudioAdapter(transport=transport)
    if key in ("elevenlabs-audio", "openai-audio"):
        definition = DEFINITIONS.get(key)
        missing = definition.missing_env() if definition else []
        if missing:
            raise ProviderNotConfigured(key, missing)
        raise AdapterNotImplemented(key)
    if key == "local":
        api_url = _env("LOCAL_VIDEO_API_URL")
        if not api_url:
            raise ProviderNotConfigured("local", ["LOCAL_VIDEO_API_URL"])
        from .local import LocalVideoAdapter
        return LocalVideoAdapter(api_url, api_key=_env("LOCAL_VIDEO_API_KEY"), transport=transport)
    if key in ("gemini-omni-flash", "higgsfield"):
        definition = DEFINITIONS.get(key)
        missing = definition.missing_env() if definition else []
        if missing:
            raise ProviderNotConfigured(key, missing)
        raise AdapterNotImplemented(key)
    if key == "test-echo":
        if (env("STUDIO_TEST_PROVIDER") or "").lower() not in ("1", "true", "yes"):
            raise ProviderNotConfigured("test-echo", ["STUDIO_TEST_PROVIDER=1"])
        from .test_echo import TestEchoAdapter
        return TestEchoAdapter(transport=transport)
    raise ValueError(f"Unknown provider key: {key}")


def test_provider_enabled() -> bool:
    return (env("STUDIO_TEST_PROVIDER") or "").lower() in ("1", "true", "yes")


void = DEFINITIONS  # keep registry import for capability lookups
