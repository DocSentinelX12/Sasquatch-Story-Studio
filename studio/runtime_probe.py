"""Host capability and engine availability probing.

A probe observes the configured runtime entrypoint. It never promotes an engine
to production verification. Production eligibility still requires a real
verification run plus checkpoint and license evidence.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .engine_registry import ENGINE_CATALOG, EngineSpec


@dataclass(frozen=True)
class RuntimeStatus:
    engine_id: str
    available: bool
    executable: str | None
    reason: str


def _entrypoint(engine: EngineSpec, root: Path | None) -> tuple[bool, str | None, str]:
    if engine.execution_mode == "service":
        return False, None, "cataloged service requires its dedicated configured adapter; process probing is not valid"
    if not engine.runtime_command:
        return False, None, "no runtime command recorded"
    executable = engine.runtime_command[0]
    resolved = shutil.which(executable)
    if resolved is None:
        return False, None, f"missing executable: {executable}"
    if executable in {"python", "python3"} and len(engine.runtime_command) > 1:
        if root is None:
            return False, resolved, "Python runtime exists but no engine root was configured for its entrypoint"
        entrypoint = root / engine.runtime_command[1]
        if not entrypoint.is_file():
            return False, resolved, f"missing configured engine entrypoint: {entrypoint}"
    return True, resolved, "configured runtime entrypoint is present; production verification still required"


def probe_engines(
    *,
    engine_roots: dict[str, str | Path] | None = None,
    engines: tuple[EngineSpec, ...] = ENGINE_CATALOG,
) -> tuple[RuntimeStatus, ...]:
    roots = {key: Path(value).expanduser().resolve() for key, value in (engine_roots or {}).items()}
    statuses = []
    for engine in engines:
        available, executable, reason = _entrypoint(engine, roots.get(engine.id))
        statuses.append(RuntimeStatus(engine.id, available, executable, reason))
    return tuple(statuses)


def require_engine(engine_id: str, *, engine_roots: dict[str, str | Path] | None = None) -> RuntimeStatus:
    status = next((item for item in probe_engines(engine_roots=engine_roots) if item.engine_id == engine_id), None)
    if status is None:
        raise KeyError(engine_id)
    if not status.available:
        raise RuntimeError(f"Required engine unavailable: {engine_id}; {status.reason}")
    return status
