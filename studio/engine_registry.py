"""Engine catalog and evidence-backed runtime verification registry."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
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
    EngineSpec("ltx-video", "0.9.8", "https://github.com/Lightricks/LTX-Video", "Apache-2.0 repository; checkpoint license must be verified for the selected model", ("video_generation",), ("python", "inference.py"), "high", True),
    EngineSpec("opentoonz", "current", "https://github.com/opentoonz/opentoonz", "BSD-3-Clause", ("animation", "compositing"), ("OpenToonz",), "professional_2d"),
    EngineSpec("blender", "current", "https://github.com/blender/blender", "GPL-3.0-or-later", ("animation", "rendering", "compositing", "editing"), ("blender", "-b"), "professional_3d"),
    EngineSpec("comfyui", "current", "https://github.com/Comfy-Org/ComfyUI", "GPL-3.0", ("image_generation", "video_generation"), ("python", "main.py"), "high"),
    EngineSpec("ace-step-1.5", "1.5", "https://github.com/ace-step/ACE-Step-1.5", "MIT", ("music", "sfx"), ("python", "-m", "acestep.api_server"), "very_high", execution_mode="service"),
    EngineSpec("piper", "current", "https://github.com/OHF-Voice/piper1-gpl", "GPL-3.0-or-later; individual voice/model licenses must be checked", ("voice",), ("piper",), "production_tts", True),
    EngineSpec("rhubarb-lip-sync", "1.14.x", "https://github.com/DanielSWolf/rhubarb-lip-sync", "MIT", ("lip_sync",), ("rhubarb",), "professional_2d"),
)

CATALOG_ENGINES = ENGINE_CATALOG
VERIFIED_ENGINES: tuple[EngineSpec, ...] = ()


def get_catalog_engine(engine_id: str) -> EngineSpec:
    for engine in ENGINE_CATALOG:
        if engine.id == engine_id:
            return engine
    raise KeyError(f"Unknown engine catalog entry: {engine_id}")


def get_engine(engine_id: str) -> EngineSpec:
    for engine in VERIFIED_ENGINES:
        if engine.id == engine_id:
            assert_verified_engine(engine)
            return engine
    raise KeyError(f"Engine is not runtime verified for production: {engine_id}")


def engines_for(capability: str) -> tuple[EngineSpec, ...]:
    return tuple(e for e in VERIFIED_ENGINES if capability in e.capabilities)


def catalog_engines_for(capability: str) -> tuple[EngineSpec, ...]:
    return tuple(e for e in ENGINE_CATALOG if capability in e.capabilities)


def assert_verified_engine(engine: EngineSpec) -> None:
    if not (engine.runtime_verified and engine.license_verified and engine.checkpoint_verified):
        raise RuntimeError(f"Engine {engine.id} lacks required runtime, license, or checkpoint verification evidence")
    if not engine.official_source or not engine.license or engine.quality_tier == "generic":
        raise RuntimeError(f"Unacceptable production engine: {engine.id}")
    if not engine.verification_evidence:
        raise RuntimeError(f"Engine {engine.id} has no verification evidence record")


def verified_engine(
    engine_id: str,
    *,
    runtime_evidence: str,
    license_evidence: str,
    checkpoint_evidence: str,
) -> EngineSpec:
    if not runtime_evidence or not license_evidence or not checkpoint_evidence:
        raise ValueError("runtime, license, and checkpoint evidence are required")
    return replace(
        get_catalog_engine(engine_id),
        runtime_verified=True,
        license_verified=True,
        checkpoint_verified=True,
        verification_evidence=f"runtime={runtime_evidence}; license={license_evidence}; checkpoint={checkpoint_evidence}",
    )


@dataclass(frozen=True)
class EngineVerificationRecord:
    engine_id: str
    engine_version: str
    executable: str
    version_observation: str
    checkpoint_path: str
    checkpoint_sha256: str
    license_source: str
    license_evidence: str
    runtime_output_sha256: str
    recorded_at: int

    def __post_init__(self) -> None:
        required = {
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "executable": self.executable,
            "version_observation": self.version_observation,
            "checkpoint_path": self.checkpoint_path,
            "checkpoint_sha256": self.checkpoint_sha256,
            "license_source": self.license_source,
            "license_evidence": self.license_evidence,
            "runtime_output_sha256": self.runtime_output_sha256,
        }
        if any(not value.strip() for value in required.values()):
            raise ValueError("complete engine verification evidence is required")
        for field_name in ("checkpoint_sha256", "runtime_output_sha256"):
            value = getattr(self, field_name)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
                raise ValueError(f"{field_name} must be a SHA-256 hex digest")
        if self.recorded_at < 0:
            raise ValueError("recorded_at cannot be negative")

    def to_engine(self) -> EngineSpec:
        engine = get_catalog_engine(self.engine_id)
        promoted = replace(
            engine,
            version_family=self.engine_version,
            runtime_verified=True,
            license_verified=True,
            checkpoint_verified=True,
            verification_evidence=(
                f"executable={self.executable}; version={self.version_observation}; "
                f"checkpoint={self.checkpoint_path}:{self.checkpoint_sha256}; "
                f"runtime_output_sha256={self.runtime_output_sha256}; "
                f"license_source={self.license_source}; license_evidence={self.license_evidence}"
            ),
        )
        assert_verified_engine(promoted)
        return promoted


class SQLiteEngineVerificationStore:
    """Durable creator-owned evidence records. It never creates verification itself."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS engine_verification ("
                "engine_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def save(self, record: EngineVerificationRecord) -> None:
        payload = json.dumps(record.__dict__, sort_keys=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO engine_verification(engine_id, payload) VALUES (?, ?) "
                "ON CONFLICT(engine_id) DO UPDATE SET payload=excluded.payload",
                (record.engine_id, payload),
            )

    def load(self, engine_id: str) -> EngineVerificationRecord | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload FROM engine_verification WHERE engine_id=?", (engine_id,)
            ).fetchone()
        if row is None:
            return None
        return EngineVerificationRecord(**json.loads(row[0]))

    def snapshot(self) -> tuple[EngineVerificationRecord, ...]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT payload FROM engine_verification ORDER BY engine_id").fetchall()
        return tuple(EngineVerificationRecord(**json.loads(row[0])) for row in rows)


class RuntimeEngineRegistry:
    """Resolve production engines only from persisted evidence records."""

    def __init__(self, store: SQLiteEngineVerificationStore):
        self.store = store

    def get(self, engine_id: str) -> EngineSpec:
        record = self.store.load(engine_id)
        if record is None:
            raise KeyError(f"Engine has no persisted runtime verification: {engine_id}")
        return record.to_engine()

    def verified_engines(self) -> tuple[EngineSpec, ...]:
        return tuple(record.to_engine() for record in self.store.snapshot())


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


def catalog_license_record(engine_id: str) -> LicenseRecord:
    engine = get_catalog_engine(engine_id)
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
