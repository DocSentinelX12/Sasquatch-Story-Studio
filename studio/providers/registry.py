"""Provider registry: declarative definitions for AI media providers.

This registry is metadata + honest status reporting. It performs no network
calls. A provider is "ready" ONLY when its required credentials exist in the
server environment AND a real adapter implementation is present. Stubs exist so
configuration, status and error states are real — they never fake a generation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..config import env_is_set


class ProviderNotConfigured(RuntimeError):
    """Raised when a provider is used without complete server-side credentials."""

    def __init__(self, key: str, missing_env: list[str]) -> None:
        self.provider_key = key
        self.missing_env = missing_env
        super().__init__(
            f"Provider '{key}' is not configured. "
            f"Missing environment variables: {', '.join(missing_env)}. "
            "Add them to the server-side .env file and restart the studio."
        )


class AdapterNotImplemented(RuntimeError):
    """Raised when credentials exist but no real adapter integration has been built."""

    def __init__(self, key: str) -> None:
        self.provider_key = key
        super().__init__(
            f"Provider '{key}' has credentials configured, but its real adapter "
            "integration is not implemented in this phase. See "
            "docs/PROVIDER_INTEGRATION.md for the adapter contract."
        )


@dataclass(frozen=True)
class ProviderDefinition:
    key: str
    display_name: str
    kind: str                                    # video | voice | music | image
    required_env: tuple[str, ...] = field(default_factory=tuple)
    optional_env: tuple[str, ...] = field(default_factory=tuple)
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    docs_url: str = ""
    notes: str = ""
    adapter_module: str = ""

    def missing_env(self, environ: dict[str, str] | None = None) -> list[str]:
        lookup = environ if environ is not None else dict(os.environ)
        missing = []
        for name in self.required_env:
            value = lookup.get(name)
            if value is None or value.strip() == "":
                # fall back to the .env loader for names not in os.environ
                if not env_is_set(name):
                    missing.append(name)
        return missing

    def status(self) -> str:
        return "not_configured" if self.missing_env() else "ready"


# NOTE: required_env names are a configuration CONTRACT, not a claim that any
# vendor API is reachable or that an adapter exists. Adapt when integrating.
DEFINITIONS: dict[str, ProviderDefinition] = {
    d.key: d
    for d in (
        ProviderDefinition(
            key="seedance",
            display_name="Seedance (ByteDance)",
            kind="video",
            required_env=("SEEDANCE_API_KEY",),
            optional_env=("SEEDANCE_API_BASE_URL",),
            capabilities=("image-to-video", "text-to-video", "reference-guided generation"),
            docs_url="https://www.volcengine.com/docs/85621",
            notes=(
                "Video generation provider. Requires a server-side API key. "
                "No adapter is connected in Phase 1; the contract and job queue are ready."
            ),
            adapter_module="studio.providers.adapters.seedance",
        ),
        ProviderDefinition(
            key="veo",
            display_name="Google Veo",
            kind="video",
            required_env=("GEMINI_API_KEY",),
            optional_env=("VEO_PROJECT_ID", "VEO_LOCATION"),
            capabilities=("text-to-video", "image-to-video", "cinematic camera control"),
            docs_url="https://ai.google.dev/gemini-api/docs/video",
            notes=(
                "Google Veo video generation (Gemini API credential). "
                "No adapter is connected in Phase 1; configuration contract is defined."
            ),
            adapter_module="studio.providers.adapters.veo",
        ),
        ProviderDefinition(
            key="wan",
            display_name="Wan (Alibaba)",
            kind="video",
            required_env=("WAN_API_KEY",),
            optional_env=("WAN_API_BASE_URL",),
            capabilities=("text-to-video", "image-to-video"),
            docs_url="https://github.com/Wan-Video",
            notes=(
                "Open video-generation model family (hosted or self-run endpoints). "
                "No adapter is connected in Phase 1; configuration contract is defined."
            ),
            adapter_module="studio.providers.adapters.wan",
        ),
        # --- Phase 3: story/text assistance providers (contracts only) -------
        ProviderDefinition(
            key="openai-text",
            display_name="OpenAI (story assistance)",
            kind="story",
            required_env=("OPENAI_API_KEY",),
            optional_env=("OPENAI_TEXT_MODEL",),
            capabilities=(
                "generate story ideas", "expand story", "generate outline",
                "improve dialogue", "generate scene descriptions", "generate shot suggestions",
            ),
            docs_url="https://platform.openai.com/docs",
            notes=(
                "Language-model provider for future story assistance. No adapter is "
                "connected; manual writing always works without it."
            ),
            adapter_module="studio.providers.adapters.text_stubs",
        ),
        ProviderDefinition(
            key="anthropic-text",
            display_name="Anthropic (story assistance)",
            kind="story",
            required_env=("ANTHROPIC_API_KEY",),
            optional_env=("ANTHROPIC_TEXT_MODEL",),
            capabilities=(
                "generate story ideas", "expand story", "generate outline",
                "improve dialogue", "generate scene descriptions", "generate shot suggestions",
            ),
            docs_url="https://docs.anthropic.com",
            notes="Language-model provider for future story assistance. Not connected.",
            adapter_module="studio.providers.adapters.text_stubs",
        ),
        ProviderDefinition(
            key="gemini-text",
            display_name="Google Gemini (story assistance)",
            kind="story",
            required_env=("GEMINI_API_KEY",),
            optional_env=("GEMINI_TEXT_MODEL",),
            capabilities=(
                "generate story ideas", "expand story", "generate outline",
                "improve dialogue", "generate scene descriptions", "generate shot suggestions",
            ),
            docs_url="https://ai.google.dev/gemini-api/docs",
            notes="Language-model provider for future story assistance. Not connected.",
            adapter_module="studio.providers.adapters.text_stubs",
        ),
    )
}


def get_definition(key: str) -> ProviderDefinition | None:
    return DEFINITIONS.get(key)


def provider_status_list() -> list[dict]:
    """Status for every registered provider. Never includes credential values."""
    return [
        {
            "key": d.key,
            "display_name": d.display_name,
            "kind": d.kind,
            "status": d.status(),
            "missing_env": d.missing_env(),          # names only
            "required_env": list(d.required_env),    # names only
            "optional_env": list(d.optional_env),
            "capabilities": list(d.capabilities),
            "docs_url": d.docs_url,
            "notes": d.notes,
            "adapter_connected": False,              # honest until a real adapter ships
        }
        for d in DEFINITIONS.values()
    ]
