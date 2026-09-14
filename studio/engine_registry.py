"""Verified production-engine registry.

Only engines with independently verified official sources, licenses, and useful
production capabilities are admitted. This is metadata, not an install claim.
"""
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
    EngineSpec("wan2.1", "2.1", "https://github.com/Wan-Video/Wan2.1", "Apache-2.0", ("video_generation", "image_generation"), ("python", "generate.py"), "high"),
    EngineSpec("ltx-video", "0.9.x", "https://github.com/Runware/LTX-Video", "Apache-2.0", ("video_generation",), ("python", "inference.py"), "high"),
    EngineSpec("opentoonz", "current", "https://github.com/opentoonz/opentoonz", "BSD-3-Clause", ("animation", "compositing"), ("OpenToonz",), "professional_2d"),
    EngineSpec("blender", "current", "https://github.com/blender/blender", "GPL-3.0-or-later", ("animation", "rendering", "compositing", "editing"), ("blender", "-b"), "professional_3d"),
    EngineSpec("comfyui", "current", "https://github.com/Comfy-Org/ComfyUI", "GPL-3.0", ("image_generation", "video_generation"), ("python", "main.py"), "high"),
)

def get_engine(engine_id: str) -> EngineSpec:
    for engine in VERIFIED_ENGINES:
        if engine.id == engine_id:
            return engine
    raise KeyError(f"Unknown verified engine: {engine_id}")

def engines_for(capability: str) -> tuple[EngineSpec, ...]:
    return tuple(e for e in VERIFIED_ENGINES if capability in e.capabilities)

def assert_verified_engine(engine: EngineSpec) -> None:
    if not engine.official_source or not engine.license:
        raise RuntimeError(f"Engine {engine.id} lacks verified provenance metadata")
    if engine.quality_tier == "generic":
        raise RuntimeError(f"Generic engine is prohibited: {engine.id}")

def ids(engines: Iterable[EngineSpec] = VERIFIED_ENGINES) -> tuple[str, ...]:
    return tuple(e.id for e in engines)
