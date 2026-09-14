"""Host capability and verified-engine availability probing."""
from __future__ import annotations
import shutil
from dataclasses import dataclass
from .engine_registry import VERIFIED_ENGINES

@dataclass(frozen=True)
class RuntimeStatus:
    engine_id: str
    available: bool
    executable: str | None
    reason: str

def probe_engines() -> tuple[RuntimeStatus, ...]:
    statuses = []
    for engine in VERIFIED_ENGINES:
        executable = shutil.which(engine.runtime_command[0])
        statuses.append(RuntimeStatus(engine.id, executable is not None, executable, "available" if executable else f"missing executable: {engine.runtime_command[0]}"))
    return tuple(statuses)

def require_engine(engine_id: str) -> RuntimeStatus:
    status = next((item for item in probe_engines() if item.engine_id == engine_id), None)
    if status is None:
        raise KeyError(engine_id)
    if not status.available:
        raise RuntimeError(f"Required verified engine unavailable: {engine_id}; {status.reason}")
    return status
