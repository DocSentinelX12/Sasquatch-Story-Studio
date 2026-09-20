"""Verification-backed engine contract for distributed production launches."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .distributed_execution import DistributedLaunchSpec
from .engine_adapters import ProcessAdapter
from .engine_registry import RuntimeEngineRegistry
from .production import ProductionRequest


def _request_value(request: ProductionRequest, name: str) -> object | None:
    return request.parameters.get(name, request.payload.get(name))


def build_verified_distributed_launch_spec(
    registry: RuntimeEngineRegistry,
    adapter: ProcessAdapter,
    request: ProductionRequest,
    allocation: Any,
    rendezvous_id: str,
    rendezvous_host: str,
    rendezvous_port: int,
) -> DistributedLaunchSpec:
    """Derive a distributed launch only from persisted distributed verification evidence.

    No caller-supplied executable or application command is accepted here. The
    verified adapter command is the only command source, and distributed mode
    must have its own persisted verification evidence before this seam can run.
    """
    engine = registry.get(adapter.info.id)
    record = registry.store.load(adapter.info.id)
    if not (engine.runtime_verified and engine.license_verified and engine.checkpoint_verified):
        raise RuntimeError("engine is not fully verified for production")
    if record is None or not record.distributed_execution_verified:
        raise RuntimeError(f"engine {adapter.info.id} lacks distributed execution verification evidence")
    if record.distributed_launch_mode != "torchrun":
        raise ValueError("verified distributed launch mode must be torchrun")
    if not record.distributed_runtime_output_sha256:
        raise RuntimeError("distributed execution verification is missing runtime evidence")
    if allocation.node_count < 2 or len(allocation.worker_ids) < 2:
        raise ValueError("distributed production requires at least two workers")

    command: list[str] = []
    for item in adapter.command:
        if not command and item in {"torchrun", "python"}:
            continue
        if item == "{prompt}":
            value = _request_value(request, "prompt")
            if not isinstance(value, str) or not value.strip():
                raise ValueError("distributed production request requires prompt")
            command.append(value)
        elif item == "{image_path}":
            value = _request_value(request, "image_path")
            if not isinstance(value, (str, Path)):
                raise ValueError("distributed production request requires image_path")
            command.append(str(Path(value).expanduser().resolve()))
        elif item == "{reference_images}":
            value = _request_value(request, "reference_images")
            if not isinstance(value, (list, tuple)) or not value:
                raise ValueError("distributed production request requires reference_images")
            if any(not isinstance(v, (str, Path)) for v in value):
                raise ValueError("reference_images entries must be paths")
            command.append(",".join(str(Path(v).expanduser().resolve()) for v in value))
        else:
            command.append(item)

    if not command:
        raise ValueError("verified engine command contains no application command")
    if "torchrun" in command:
        raise ValueError("verified distributed application command cannot embed a second torchrun")
    return DistributedLaunchSpec(
        executable="torchrun",
        command=tuple(command),
        rendezvous_id=rendezvous_id,
        rendezvous_host=rendezvous_host,
        rendezvous_port=rendezvous_port,
        timeout_seconds=adapter.timeout_seconds,
        output_path=adapter.output_path,
    )
