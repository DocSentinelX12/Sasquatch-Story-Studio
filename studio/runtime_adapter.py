"""Real local-process adapter for verified production engines.

Never simulates success: missing runtimes, failures, and missing outputs are hard failures.
"""
from __future__ import annotations
import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from .adapters import AdapterInfo
from .engine_registry import EngineSpec, assert_verified_engine
from .production import ProductionRequest, ProductionResponse

@dataclass(frozen=True)
class LocalEngineAdapter:
    engine: EngineSpec
    executable: str | None = None
    timeout_seconds: int = 3600

    @property
    def info(self) -> AdapterInfo:
        assert_verified_engine(self.engine)
        return AdapterInfo(self.engine.id, self.engine.version_family, self.engine.license, self.engine.capabilities, True)

    def _resolve_executable(self) -> str:
        candidate = self.executable or self.engine.runtime_command[0]
        resolved = shutil.which(candidate)
        if resolved is None:
            raise RuntimeError(f"Verified engine {self.engine.id} is not installed or not on PATH: {candidate}")
        return resolved

    def execute(self, request: ProductionRequest) -> ProductionResponse:
        if request.stage not in _supported_stages(self.engine.capabilities):
            raise RuntimeError(f"Engine {self.engine.id} cannot execute stage {request.stage}")
        payload = request.payload
        workdir = Path(str(payload.get("workdir", ""))).expanduser().resolve()
        if not workdir.is_dir():
            raise RuntimeError(f"Engine workdir does not exist: {workdir}")
        args = payload.get("args", [])
        if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
            raise ValueError("Production engine args must be a list of strings")
        command = [self._resolve_executable(), *self.engine.runtime_command[1:], *args]
        env = os.environ.copy()
        env["SASQUATCH_CANONICAL_SOURCE_HASH"] = request.canonical_source_hash
        if request.seed is not None:
            env["SASQUATCH_SEED"] = str(request.seed)
        completed = subprocess.run(command, cwd=workdir, env=env, capture_output=True, text=True, timeout=self.timeout_seconds, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"Engine {self.engine.id} failed with exit {completed.returncode}: {completed.stderr[-4000:]}")
        output_refs = _validated_outputs(payload.get("outputs", []), workdir)
        provenance = {"engine_id": self.engine.id, "engine_version_family": self.engine.version_family, "official_source": self.engine.official_source, "license": self.engine.license, "canonical_source_hash": request.canonical_source_hash, "command": command, "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest()}
        return ProductionResponse(self.engine.id, tuple(output_refs), provenance)

def _supported_stages(capabilities: Sequence[str]) -> set[str]:
    mapping = {"video_generation": {"animate"}, "image_generation": {"resolve_assets", "animate"}, "animation": {"animate"}, "compositing": {"composite"}}
    return set().union(*(mapping.get(capability, set()) for capability in capabilities))

def _validated_outputs(outputs: Any, workdir: Path) -> list[str]:
    if not isinstance(outputs, list):
        raise ValueError("Production request outputs must be a list")
    validated: list[str] = []
    for raw in outputs:
        if not isinstance(raw, str) or not raw:
            raise ValueError("Each production output must be a non-empty relative path")
        path = (workdir / raw).resolve()
        if workdir not in path.parents:
            raise RuntimeError(f"Output escapes engine workdir: {raw}")
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Declared production output is missing or empty: {raw}")
        validated.append(str(path))
    return validated
