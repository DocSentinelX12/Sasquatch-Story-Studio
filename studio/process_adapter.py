"""Real subprocess-backed production adapter with explicit execution evidence."""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .adapters import AdapterInfo, require_verified
from .production import ProductionRequest, ProductionResponse


@dataclass(frozen=True)
class ProcessAdapter:
    """Execute an explicitly configured engine command and require real output.

    The command may contain ``{output}``, ``{prompt}``, ``{image_path}``, or
    ``{reference_images}``. ``output`` is always required when the command uses
    an explicit token. Prompt and image values are taken from request parameters
    first, then the request payload. Existing commands without these tokens
    retain their prior behavior.
    """

    adapter_id: str
    version: str
    license_name: str
    capabilities: tuple[str, ...]
    command: tuple[str, ...]
    output_path: str
    working_directory: str | None = None
    verified: bool = False
    timeout_seconds: int = 3600
    quality_tier: str = "generic"
    commercial_use_review_required: bool = False
    is_local: bool = True
    uses_paid_service: bool = False
    uses_paid_api: bool = False
    source_revision: str | None = None
    checkpoint_path: str | None = None
    checkpoint_sha256: str | None = None
    runtime_output_sha256: str | None = None

    @property
    def info(self) -> AdapterInfo:
        return AdapterInfo(
            self.adapter_id,
            self.version,
            self.license_name,
            self.capabilities,
            self.verified,
        )

    @staticmethod
    def _request_value(request: ProductionRequest, name: str) -> object | None:
        if name in request.parameters:
            return request.parameters[name]
        return request.payload.get(name)

    @staticmethod
    def _reference_images(value: object | None) -> str:
        if isinstance(value, (str, Path)):
            values = [value]
        elif isinstance(value, (list, tuple)):
            values = list(value)
        else:
            raise ValueError("reference_images must be a path string or a list/tuple of paths")
        if not values:
            raise ValueError("reference_images must contain at least one path")
        if any(not isinstance(item, (str, Path)) for item in values):
            raise ValueError("reference_images entries must be path strings")
        return ",".join(str(Path(item).expanduser().resolve()) for item in values)

    def execute(self, request: ProductionRequest) -> ProductionResponse:
        require_verified(self)
        if not self.command or any(not item for item in self.command):
            raise RuntimeError(f"Engine {self.adapter_id} has no executable command configured")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")

        output = Path(str(request.parameters.get("output_path", self.output_path))).expanduser().resolve()
        workdir = Path(self.working_directory).expanduser().resolve() if self.working_directory else None
        if workdir is not None and not workdir.is_dir():
            raise RuntimeError(f"engine working directory does not exist: {workdir}")
        output.parent.mkdir(parents=True, exist_ok=True)

        prompt = self._request_value(request, "prompt")
        image_path = self._request_value(request, "image_path")
        reference_images = self._request_value(request, "reference_images")
        command: list[str] = []
        for item in self.command:
            if item == "{output}":
                command.append(str(output))
            elif item == "{prompt}":
                if not isinstance(prompt, str) or not prompt.strip():
                    raise ValueError(f"engine {self.adapter_id} requires a non-empty prompt parameter")
                command.append(prompt)
            elif item == "{image_path}":
                if image_path is None:
                    command.append("none")
                elif isinstance(image_path, (str, Path)):
                    command.append(str(Path(image_path).expanduser().resolve()))
                else:
                    raise ValueError(f"engine {self.adapter_id} image_path must be a path string")
            elif item == "{reference_images}":
                command.append(self._reference_images(reference_images))
            else:
                command.append(item)
        if "{output}" not in self.command:
            command.append(str(output))

        try:
            completed = subprocess.run(
                tuple(command),
                cwd=workdir,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout_seconds,
                env=os.environ.copy(),
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"engine executable is unavailable: {self.command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"engine {self.adapter_id} exceeded execution timeout") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"engine {self.adapter_id} failed with exit code {completed.returncode}: {detail}")
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(f"engine {self.adapter_id} exited successfully but produced no output artifact")

        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        return ProductionResponse(
            self.adapter_id,
            (str(output),),
            {
                "execution": "subprocess",
                "engine_id": self.adapter_id,
                "engine_version": self.version,
                "license": self.license_name,
                "quality_tier": self.quality_tier,
                "commercial_use_review_required": self.commercial_use_review_required,
                "canonical_source_hash": request.canonical_source_hash,
                "output_sha256": digest,
                "verified_checkpoint_path": self.checkpoint_path,
                "verified_checkpoint_sha256": self.checkpoint_sha256,
                "verified_source_revision": self.source_revision,
                "verified_runtime_output_sha256": self.runtime_output_sha256,
                "exit_code": completed.returncode,
            },
        )
