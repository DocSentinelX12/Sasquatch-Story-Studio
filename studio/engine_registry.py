"""Engine catalog and runtime-verification registry.

Catalog metadata is not proof that an engine is installed or executable. An
engine becomes production-eligible only after a worker records real execution
and licensing evidence for the exact version/checkpoint in use.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from .licensing import CommercialStatus, LicenseRecord


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
    execution_mode: str = "process"
    runtime_verified: bool = False
    license_verified: bool = False
    checkpoint_verified: bool = False
    verification_evidence: str | None = None


ENGINE_CATALOG: tuple[EngineSpec, ...] = (
    EngineSpec("wan2.2", "2.2", "https://github.com/Wan-Video/Wan2.2", "Apache-2.0", ("video_generation", "image_generation"), ("python", "generate.py"), "very_high"),
    EngineSpec("wan2.1", "2.1", "https://github.com/Wan-Video/Wan2.1", "Apache-2.0", ("video_generation", "image_generation"), ("python", "generate.py"), "high"),
    EngineSpec("ltx-video", "0.9.x", "https://github.com/Runware/LTX-Video", "Apache-2.0 repository; OpenRail-M for v0.9.5 checkpoint", ("video_generation",), ("python", "inference.py"), "high", True),
    EngineSpec("opentoonz", "current", "https://github.com/opentoonz/opentoonz", "BSD-3-Clause", ("animation", "compositing"), ("OpenToonz",), "professional_2d"),
    EngineSpec("blender", "current", "https://github.com/blender/blender", "GPL-3.0-or-later", ("animation", "rendering", "compositing", "editing"), ("blender", "-b"), "professional_3d"),
    EngineSpec("comfyui", "current", "https://github.com/Comfy-Org/ComfyUI", "GPL-3.0", ("image_generation", "video_generation"), ("python", "main.py"), "high"),
    EngineSpec("ace-step-1.5", "1.5", "https://github.com/ace-step/ACE-Step-1.5", "MIT", ("music", "sfx"), ("python", "-m", "acestep.api_server"), "very_high", execution_mode="service"),
    EngineSpec("piper", "current", "https://github.com/OHF-Voice/piper1-gpl", "GPL-3.0-or-later; individual voice/model licenses must be checked", ("voice",), ("piper",), "production_tts", True),
    EngineSpec("rhubarb-lip-sync", "1.14.x", "https://github.com/DanielSWolf/rhubarb-lip-sync", "MIT", ("lip_sync",), ("rhubarb",), "professional_2d"),
)

CATALOG_ENGINES = ENGINE_CATALOG

# Nothing is production-verified merely because it appears in the catalog.
VERIFIED_ENGINES: tuple[EngineSpec, ...] = ()


def get_catalog_engine(engine_id: str) -> EngineSpec:
    for engine in ENGINE_CATALOG:
        if engine.id == engine_id:
            return engine
    raise KeyError(f"Unknown engine catalog entry: {engine_id}")


def get_engine(engine_id: str) -> EngineSpec:
    for engine in VERIFIED_ENGINES:
        if engine.id == engine_id:
            return engine
    raise KeyError(f"Engine is not runtime verified for production: {engine_id}")


def engines_for(capability: str) -> tuple[EngineSpec, ...]:
    return tuple(e for e in VERIFIED_ENGINES if capability in e.capabilities)


def assert_verified_engine(engine: EngineSpec) -> None:
    if not (engine.runtime_verified and engine.license_verified and engine.checkpoint_verified):
        raise RuntimeError(f"Engine {engine.id} lacks required runtime, license, or checkpoint verification evidence")
    if not engine.official_source or not engine.license or engine.quality_tier == "generic":
        raise RuntimeError(f"Unacceptable production engine: {engine.id}")


def verified_engine(
    engine_id: str,
    *,
    runtime_evidence: str,
    license_evidence: str,
    checkpoint_evidence: str,
) -> EngineSpec:
    """Promote a catalog entry only when all real evidence is supplied."""
    if not runtime_evidence or not license_evidence or not checkpoint_evidence:
        raise ValueError("runtime, license, and checkpoint evidence are required")
    return replace(
        get_catalog_engine(engine_id),
        runtime_verified=True,
        license_verified=True,
        checkpoint_verified=True,
        verification_evidence=f"runtime={runtime_evidence}; license={license_evidence}; checkpoint={checkpoint_evidence}",
    )


def license_record(engine_id: str) -> LicenseRecord:
    engine = get_engine(engine_id)
    status = CommercialStatus.REVIEW_REQUIRED if engine.commercial_use_review_required else CommercialStatus.ALLOWED
    return LicenseRecord(
        subject_id=engine.id,
        subject_version=engine.version_family,
        official_source=engine.official_source,
        license_name=engine.license,
        commercial_status=status,
        territory_restriction=engine.territory_restriction,
    )


def ids(engines: Iterable[EngineSpec] = VERIFIED_ENGINES) -> tuple[str, ...]:
    return tuple(e.id for e in engines)
