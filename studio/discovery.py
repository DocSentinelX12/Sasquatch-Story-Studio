"""Real local worker discovery with hard no-invention rules."""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

from .engine_registry import EngineSpec, VERIFIED_ENGINES
from .resources import ComputeResource


def _memory_bytes() -> int:
    if platform.system() == "Linux":
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    return 0


def _gpu_info() -> tuple[tuple[str, ...], int, int]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return (), 0, 0
    import subprocess

    result = subprocess.run(
        [executable, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        return (), 0, 0
    models: list[str] = []
    total_vram = 0
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 2 or not fields[0]:
            continue
        try:
            memory_mib = int(fields[1])
        except ValueError:
            continue
        models.append(fields[0])
        total_vram += memory_mib * 1024**2
    return tuple(models), len(models), total_vram


def _engine_is_installed(engine: EngineSpec, root: Path | None) -> bool:
    if engine.execution_mode == "service":
        return False
    if not engine.runtime_command:
        return False
    executable = engine.runtime_command[0]
    if executable in {"python", "python3"}:
        if root is None:
            return False
        entrypoint = root / engine.runtime_command[1] if len(engine.runtime_command) > 1 else None
        return entrypoint is not None and entrypoint.is_file()
    return shutil.which(executable) is not None


def discover_compute_resource(
    worker_id: str,
    *,
    engine_roots: dict[str, str | Path] | None = None,
    engines: tuple[EngineSpec, ...] = VERIFIED_ENGINES,
) -> ComputeResource:
    """Discover only capacity and engines actually observable on this machine."""
    if not worker_id.strip():
        raise ValueError("worker id is required")
    gpu_models, gpu_count, vram_bytes = _gpu_info()
    roots = {key: Path(value) for key, value in (engine_roots or {}).items()}
    installed = tuple(
        engine.id
        for engine in engines
        if _engine_is_installed(engine, roots.get(engine.id))
    )
    capabilities = tuple(sorted({capability for engine in engines if engine.id in installed for capability in engine.capabilities}))
    return ComputeResource(
        id=worker_id,
        cpu_cores=max(os.cpu_count() or 1, 1),
        memory_bytes=_memory_bytes(),
        gpu_count=gpu_count,
        gpu_models=gpu_models,
        vram_bytes=vram_bytes,
        capabilities=capabilities,
        installed_engines=installed,
        logical_slots=max(os.cpu_count() or 1, 1),
        healthy=True,
    )
