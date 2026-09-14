"""Verified production-engine registry. Generic engines are prohibited."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class EngineSpec:
    id: str
    version_family: str
    official_source: str
    license: str
    capabilities: tuple[str, ...]
    runtime_command: tuple[str, ...]
    quality_tier: str
    commercial_use_review_required: bool = False
    territory_restriction: str | None = None


VERIFIED_ENGINES: tuple[EngineSpec, ...] = (
    EngineSpec(
        "wan2.2",
        "2.2",
        "https://github.com/Wan-Video/Wan2.2",
        "Apache-2.0",
        ("video_generation", "image_generation"),
        ("python", "generate.py"),
        "very_high",
    ),
    EngineSpec(
        "wan2.1",
        "2.1",
        "https://github.com/Wan-Video/Wan2.1",
        "Apache-2.0",
        ("video_generation", "image_generation"),
        ("python", "generate.py"),
        "high",
    ),
    EngineSpec(
        "ltx-video",
        "0.9.x",
        "https://github.com/Runware/LTX-Video",
        "Apache-2.0 repository; OpenRail-M for v0.9.5 checkpoint",
        ("video_generation",),
        ("python", "inference.py"),
        "high",
        True,
    ),
    EngineSpec(
        "opentoonz",
        "current",
        "https://github.com/opentoonz/opentoonz",
        "BSD-3-Clause",
        ("animation", "compositing"),
        ("OpenToonz",),
        "professional_2d",
    ),
    EngineSpec(
        "blender",
        "current",
        "https://github.com/blender/blender",
        "GPL-3.0-or-later",
        ("animation", "rendering", "compositing", "editing"),
        ("blender", "-b"),
        "professional_3d",
    ),
    EngineSpec(
        "comfyui",
        "current",
        "https://github.com/Comfy-Org/ComfyUI",
        "GPL-3.0",
        ("image_generation", "video_generation"),
        ("python", "main.py"),
        "high",
    ),
    EngineSpec(
        "piper",
        "current",
        "https://github.com/OHF-Voice/piper1-gpl",
        "GPL-3.0-or-later; individual voice/model licenses must be checked",
        ("voice",),
        ("piper",),
        "production_tts",
        True,
    ),
    EngineSpec(
        "rhubarb-lip-sync",
        "1.14.x",
        "https://github.com/DanielSWolf/rhubarb-lip-sync",
        "MIT",
        ("lip_sync",),
        ("rhubarb",),
        "professional_2d",
    ),
)


def get_engine(engine_id: str) -> EngineSpec:
    for engine in VERIFIED_ENGINES:
        if engine.id == engine_id:
            return engine
    raise KeyError(f"Unknown verified engine: {engine_id}")


def engines_for(capability: str) -> tuple[EngineSpec, ...]:
    return tuple(e for e in VERIFIED_ENGINES if capability in e.capabilities)


def assert_verified_engine(engine: EngineSpec) -> None:
    if not engine.official_source or not engine.license or engine.quality_tier == "generic":
        raise RuntimeError(f"Unacceptable production engine: {engine.id}")


def ids(engines: Iterable[EngineSpec] = VERIFIED_ENGINES) -> tuple[str, ...]:
    return tuple(e.id for e in engines)
