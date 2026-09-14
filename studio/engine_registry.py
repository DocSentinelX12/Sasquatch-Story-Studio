"""Verified production-engine registry.

Only engines whose official source, declared license, and required capability
have been independently verified belong here. This registry does not claim an
engine is installed on the host.
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
    EngineSpec(
        id="wan2.1", version_family="2.1",
        official_source="https://github.com/Wan-Video/Wan2.1",
        license="Apache-2.0",
        capabilities=("video_generation", "image_generation"),
        runtime_command=("python", "generate.py"), quality_tier="high",
    ),
    EngineSpec(
        id="ltx-video", version_family="0.9.x",
        official_source="https://github.com/Lightricks/LTX-Video",
        license="Apache-2.0", capabilities=("video_generation",),
        runtime_command=("python", "inference.py"), quality_tier="high",
    ),
    EngineSpec(
        id="opentoonz", version_family="current",
        official_source="https://github.com/opentoonz/opentoonz",
        license="BSD-3-Clause", capabilities=("animation", "compositing"),
        runtime_command=("OpenToonz",), quality_tier="professional_2d",
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
    if not engine.official_source or not engine.license:
        raise RuntimeError(f"Engine {engine.id} lacks verified provenance metadata")
    if engine.quality_tier == "generic":
        raise RuntimeError(f"Generic engine is prohibited: {engine.id}")

def ids(engines: Iterable[EngineSpec] = VERIFIED_ENGINES) -> tuple[str, ...]:
    return tuple(e.id for e in engines)
