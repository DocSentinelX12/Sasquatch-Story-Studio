"""Build production adapters from real, persisted engine verification evidence.

This module is configuration-driven. It never marks an engine verified, invents a
command, downloads a model, or silently falls back to another provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .cogvideox15_i2v_runtime import build_cogvideox15_i2v_command
from .engine_registry import EngineSpec, RuntimeEngineRegistry
from .hunyuan_runtime import build_hunyuan_command
from .ltx25_runtime import build_ltx25_command
from .ltx_video_runtime import build_ltx_video_command
from .process_adapter import ProcessAdapter
from .skyreels_v3_runtime import build_skyreels_r2v_command
from .wan22_runtime import build_wan22_command


@dataclass(frozen=True)
class VerifiedEngineRuntimeConfig:
    """Exact execution command for an engine already present in the evidence store."""

    engine_id: str
    command: tuple[str, ...]
    output_path: str
    working_directory: str | None = None
    timeout_seconds: int = 3600

    def __post_init__(self) -> None:
        if not self.engine_id.strip():
            raise ValueError("engine_id is required")
        if not self.command or any(not item for item in self.command):
            raise ValueError("an exact runtime command is required")
        if "{output}" not in self.command:
            raise ValueError("runtime command must contain the explicit {output} placeholder")
        if not self.output_path.strip():
            raise ValueError("output_path is required")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")


def build_verified_engine_adapter(
    registry: RuntimeEngineRegistry,
    config: VerifiedEngineRuntimeConfig,
) -> ProcessAdapter:
    """Turn one persisted verification record into one executable adapter."""
    engine = registry.get(config.engine_id)
    if engine.execution_mode != "process":
        raise ValueError(
            f"engine {engine.id} uses execution mode {engine.execution_mode!r}; "
            "a process adapter cannot represent it"
        )
    return _adapter_from_verified_engine(engine, config)


def build_verified_engine_adapters(
    registry: RuntimeEngineRegistry,
    configs: Sequence[VerifiedEngineRuntimeConfig],
) -> tuple[ProcessAdapter, ...]:
    """Build only adapters backed by persisted verification evidence."""
    seen: set[str] = set()
    adapters: list[ProcessAdapter] = []
    for config in configs:
        if config.engine_id in seen:
            raise ValueError(f"duplicate engine runtime configuration: {config.engine_id}")
        seen.add(config.engine_id)
        adapters.append(build_verified_engine_adapter(registry, config))
    return tuple(adapters)


def build_production_router(
    registry: RuntimeEngineRegistry,
    configs: Sequence[VerifiedEngineRuntimeConfig],
):
    """Connect verified worker engines to the studio's capability router."""
    from .production import ProductionRouter

    return ProductionRouter(list(build_verified_engine_adapters(registry, configs)))


def build_hunyuan_runtime_config(
    *,
    repository: Path,
    model_path: Path,
    output_path: str,
    torchrun_executable: str = "torchrun",
    timeout_seconds: int = 3600,
) -> VerifiedEngineRuntimeConfig:
    """Build the exact Hunyuan production command from real local paths.

    The command leaves prompt and reference-image values as explicit request
    tokens so the production adapter can bind actual shot inputs at execution
    time. Runtime verification must already exist in the registry before this
    configuration can be turned into an adapter.
    """
    command = build_hunyuan_command(
        torchrun_executable=torchrun_executable,
        repository=repository,
        model_path=model_path,
        prompt="{prompt}",
        image_path="{image_path}",
        output_token="{output}",
        seed=1,
    )
    return VerifiedEngineRuntimeConfig(
        engine_id="hunyuanvideo-1.5",
        command=command,
        output_path=output_path,
        working_directory=str(repository.expanduser().resolve()),
        timeout_seconds=timeout_seconds,
    )


def build_skyreels_r2v_runtime_config(
    *,
    repository: Path,
    model_path: Path,
    output_path: str,
    python_executable: str = "python",
    timeout_seconds: int = 3600,
) -> VerifiedEngineRuntimeConfig:
    """Build the exact SkyReels R2V production command from real local paths.

    Prompt and reference-image values remain explicit request tokens. The
    resulting adapter is still gated by persisted runtime, checkpoint, and
    license evidence before it can execute in production.
    """
    command = build_skyreels_r2v_command(
        python_executable=python_executable,
        repository=repository,
        model_path=model_path,
        prompt="{prompt}",
        reference_images=("{reference_images}",),
        output_token="{output}",
    )
    return VerifiedEngineRuntimeConfig(
        engine_id="skyreels-v3-r2v-14b",
        command=command,
        output_path=output_path,
        working_directory=str(repository.expanduser().resolve()),
        timeout_seconds=timeout_seconds,
    )


def build_cogvideox15_i2v_runtime_config(
    *,
    repository: Path,
    model_path: Path,
    output_path: str,
    python_executable: str = "python",
    timeout_seconds: int = 21600,
) -> VerifiedEngineRuntimeConfig:
    """Build the exact CogVideoX1.5 I2V command from real local paths."""
    command = build_cogvideox15_i2v_command(
        python_executable=python_executable,
        repository=repository,
        model_path=model_path,
        prompt="{prompt}",
        image_path="{image_path}",
        output_token="{output}",
    )
    return VerifiedEngineRuntimeConfig(
        engine_id="cogvideox1.5-5b-i2v",
        command=command,
        output_path=output_path,
        working_directory=str(repository.expanduser().resolve()),
        timeout_seconds=timeout_seconds,
    )


def build_wan22_runtime_config(
    *,
    repository: Path,
    model_path: Path,
    output_path: str,
    python_executable: str = "python",
    timeout_seconds: int = 21600,
) -> VerifiedEngineRuntimeConfig:
    """Build the official Wan2.2 T2V command with a dynamic Studio prompt."""
    command = build_wan22_command(
        python_executable=python_executable,
        repository=repository,
        model_path=model_path,
        prompt="{prompt}",
        output_token="{output}",
    )
    return VerifiedEngineRuntimeConfig(
        engine_id="wan2.2",
        command=command,
        output_path=output_path,
        working_directory=str(repository.expanduser().resolve()),
        timeout_seconds=timeout_seconds,
    )


def build_ltx_video_runtime_config(
    *,
    repository: Path,
    model_path: Path,
    output_path: str,
    python_executable: str = "python",
    timeout_seconds: int = 21600,
) -> VerifiedEngineRuntimeConfig:
    """Build the official LTX-Video bridge command with dynamic shot inputs."""
    command = build_ltx_video_command(
        python_executable=python_executable,
        repository=repository,
        model_path=model_path,
        prompt="{prompt}",
        image_path="{image_path}",
        output_token="{output}",
    )
    return VerifiedEngineRuntimeConfig(
        engine_id="ltx-video",
        command=command,
        output_path=output_path,
        working_directory=str(repository.expanduser().resolve()),
        timeout_seconds=timeout_seconds,
    )


def build_ltx25_runtime_config(
    *,
    studio_root: Path,
    source_repository: Path,
    model_root: Path,
    output_path: str,
    python_executable: str = "python",
    timeout_seconds: int = 21600,
) -> VerifiedEngineRuntimeConfig:
    """Build the official LTX-2.5 distilled I2V/T2V command.

    The model directory must contain the official split components. Prompt and
    image values remain request-bound tokens, and production use is still gated
    by persisted runtime, checkpoint, and license evidence.
    """
    command = build_ltx25_command(
        python_executable=python_executable,
        studio_root=studio_root.expanduser().resolve(),
        source_repository=source_repository.expanduser().resolve(),
        model_root=model_root.expanduser().resolve(),
        prompt="{prompt}",
        image_path="{image_path}",
        output_token="{output}",
    )
    return VerifiedEngineRuntimeConfig(
        engine_id="ltx-2.5",
        command=command,
        output_path=output_path,
        working_directory=str(studio_root.expanduser().resolve()),
        timeout_seconds=timeout_seconds,
    )


def _adapter_from_verified_engine(
    engine: EngineSpec,
    config: VerifiedEngineRuntimeConfig,
) -> ProcessAdapter:
    return ProcessAdapter(
        adapter_id=engine.id,
        version=engine.version_family,
        license_name=engine.license,
        capabilities=engine.capabilities,
        command=config.command,
        output_path=str(Path(config.output_path).expanduser()),
        working_directory=config.working_directory,
        verified=True,
        timeout_seconds=config.timeout_seconds,
        quality_tier=engine.quality_tier,
        commercial_use_review_required=engine.commercial_use_review_required,
        source_revision=engine.source_revision,
        checkpoint_path=engine.checkpoint_path,
        checkpoint_sha256=engine.checkpoint_sha256,
        runtime_output_sha256=engine.runtime_output_sha256,
    )


def configs_from_mapping(values: Mapping[str, Mapping[str, object]]) -> tuple[VerifiedEngineRuntimeConfig, ...]:
    """Parse worker configuration without inventing missing runtime details."""
    configs: list[VerifiedEngineRuntimeConfig] = []
    for engine_id, value in values.items():
        command = value.get("command")
        output_path = value.get("output_path")
        if not isinstance(command, (list, tuple)):
            raise ValueError(f"engine {engine_id}: command must be a list or tuple")
        if not isinstance(output_path, str):
            raise ValueError(f"engine {engine_id}: output_path is required")
        working_directory = value.get("working_directory")
        if working_directory is not None and not isinstance(working_directory, str):
            raise ValueError(f"engine {engine_id}: working_directory must be a string")
        timeout = value.get("timeout_seconds", 3600)
        if not isinstance(timeout, int):
            raise ValueError(f"engine {engine_id}: timeout_seconds must be an integer")
        configs.append(
            VerifiedEngineRuntimeConfig(
                engine_id=engine_id,
                command=tuple(str(item) for item in command),
                output_path=output_path,
                working_directory=working_directory,
                timeout_seconds=timeout,
            )
        )
    return tuple(configs)
