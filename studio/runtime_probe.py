"""Host capability and engine availability probing.

A probe observes whether a cataloged engine entrypoint is present. It never
promotes an engine to production verification. Production eligibility still
requires explicit runtime, checkpoint, and license evidence.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass

from .engine_registry import ENGINE_CATALOG


@dataclass(frozen=True)
class RuntimeStatus:
    engine_id: str
    available: bool
    executable: str | None
    reason: str


def probe_engines() -> tuple[RuntimeStatus, ...]:
    statuses = []
    for engine in ENGINE_CATALOG:
        if engine.execution_mode == "service":
            statuses.append(
                RuntimeStatus(
                    engine.id,
                    False,
                    None,
                    "cataloged service requires its dedicated configured adapter; process probing is not valid",
                )
            )
            continue
        if not engine.runtime_command:
            statuses.append(RuntimeStatus(engine.id, False, None, "no runtime command recorded"))
            continue
        executable = shutil.which(engine.runtime_command[0])
        statuses.append(
            RuntimeStatus(
                engine.id,
                executable is not None,
                executable,
                "entrypoint executable available; production verification still required"
                if executable
                else f"missing executable: {engine.runtime_command[0]}",
            )
        )
    return tuple(statuses)


def require_engine(engine_id: str) -> RuntimeStatus:
    status = next((item for item in probe_engines() if item.engine_id == engine_id), None)
    if status is None:
        raise KeyError(engine_id)
    if not status.available:
        raise RuntimeError(f"Required engine unavailable: {engine_id}; {status.reason}")
    return status
