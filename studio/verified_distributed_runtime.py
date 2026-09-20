"""Verification-backed engine contracts for distributed production launches."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .distributed_execution import DistributedLaunchSpec
from .engine_adapters import ProcessAdapter
from .engine_registry import RuntimeEngineRegistry
from .production import ProductionRequest


def _request_value(request: ProductionRequest, name: str) -> object | None:
    return request.parameters.get(name, request.payload.get(name))


def _bind_request_tokens(command: tuple[str, ...], request: ProductionRequest) -> tuple[str, ...]:
    bound: list[str] = []
    for item in command:
        if item == "{prompt}":
            value = _request_value(request, "prompt")
            if not isinstance(value, str) or not value.strip():
                raise ValueError("distributed production request requires prompt")
            bound.append(value)
        elif item == "{image_path}":
            value = _request_value(request, "image_path")
            if value is None:
                bound.append("none")
            elif isinstance(value, (str, Path)):
                bound.append(str(Path(value).expanduser().resolve()))
            else:
                raise ValueError("distributed production request image_path must be a path")
        elif item == "{reference_images}":
            value = _request_value(request, "reference_images")
            if not isinstance(value, (list, tuple)) or not value:
                raise ValueError("distributed production request requires reference_images")
            if any(not isinstance(v, (str, Path)) for v in value):
                raise ValueError("reference_images entries must be paths")
            bound.append(",".join(str(Path(v).expanduser().resolve()) for v in value))
        else:
            bound.append(item)
    return tuple(bound)


def _wan22_distributed_command(
    adapter: ProcessAdapter,
    request: ProductionRequest,
    world_size: int,
) -> tuple[str, ...]:
    """Convert the verified Wan2.2 single-node command into its distributed form.

    Wan2.2's official inference path uses torchrun, FSDP for the model and T5,
    and DeepSpeed Ulysses for sequence parallelism. Its generator requires the
    Ulysses size to equal WORLD_SIZE and the model's attention-head count to be
    evenly divisible by that size. The outer distributed launcher supplies the
    process count, so the adapter's single-node launcher and its local process
    count must not be nested.
    """
    if world_size < 2:
        raise ValueError("Wan2.2 distributed execution requires at least two processes")
    if 40 % world_size != 0:
        raise ValueError("Wan2.2 T2V-A14B requires distributed world size to divide its 40 attention heads")

    command = list(adapter.command)
    if command and command[0] == "python":
        command.pop(0)
    elif command and command[0] == "torchrun":
        raise ValueError("Wan2.2 adapter command must be the application command, not a nested torchrun launcher")

    if not command or command[0] != "generate.py":
        raise ValueError("Wan2.2 distributed execution requires the verified generate.py application command")
    if "--task" not in command or "t2v-A14B" not in command:
        raise ValueError("Wan2.2 distributed execution requires the verified t2v-A14B task")
    if "--ulysses_size" in command or "--dit_fsdp" in command or "--t5_fsdp" in command:
        raise ValueError("Wan2.2 distributed verification command must not pre-bind distributed-only flags")

    filtered: list[str] = []
    index = 0
    while index < len(command):
        item = command[index]
        if item == "--offload_model":
            if index + 1 >= len(command):
                raise ValueError("Wan2.2 --offload_model flag is missing its value")
            index += 2
            continue
        filtered.append(item)
        index += 1

    filtered.extend(("--dit_fsdp", "--t5_fsdp", "--ulysses_size", str(world_size)))
    return _bind_request_tokens(tuple(filtered), request)


def build_verified_distributed_launch_spec(
    registry: RuntimeEngineRegistry,
    adapter: ProcessAdapter,
    request: ProductionRequest,
    allocation: Any,
    rendezvous_id: str,
    rendezvous_host: str,
    rendezvous_port: int,
) -> DistributedLaunchSpec:
    """Build an engine-specific distributed launch from persisted evidence.

    A distributed engine is never inferred merely because its single-worker
    command can be wrapped in torchrun. The verification record must name the
    exact distributed launch contract, and this module implements only contracts
    that have explicit engine semantics.
    """
    engine = registry.get(adapter.info.id)
    record = registry.store.load(adapter.info.id)
    if not (engine.runtime_verified and engine.license_verified and engine.checkpoint_verified):
        raise RuntimeError("engine is not fully verified for production")
    if record is None or not record.distributed_execution_verified:
        raise RuntimeError(f"engine {adapter.info.id} lacks distributed execution verification evidence")
    if not record.distributed_runtime_output_sha256:
        raise RuntimeError("distributed execution verification is missing runtime evidence")
    if allocation.node_count < 2 or len(allocation.worker_ids) < 2:
        raise ValueError("distributed production requires at least two workers")
    if allocation.world_size < 2:
        raise ValueError("distributed production requires at least two processes")

    if adapter.info.id == "wan2.2":
        if record.distributed_launch_mode != "torchrun_wan22":
            raise ValueError("Wan2.2 distributed verification must use launch mode torchrun_wan22")
        command = _wan22_distributed_command(adapter, request, allocation.world_size)
    else:
        raise ValueError(
            f"engine {adapter.info.id} has no implemented verified distributed production contract"
        )

    return DistributedLaunchSpec(
        executable="torchrun",
        command=command,
        rendezvous_id=rendezvous_id,
        rendezvous_host=rendezvous_host,
        rendezvous_port=rendezvous_port,
        timeout_seconds=adapter.timeout_seconds,
        output_path=adapter.output_path,
    )
