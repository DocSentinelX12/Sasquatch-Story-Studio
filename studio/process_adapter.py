"""Real subprocess-backed production adapter with explicit execution evidence."""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .adapters import AdapterInfo, require_verified
from .production import ProductionRequest, ProductionResponse


@dataclass(frozen=True)
class ProcessAdapter:
    """Execute a configured local engine command and require a real output artifact.

    The command is supplied by the worker configuration. This class never invents
    an executable, downloads an engine, or substitutes another provider.
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

    @property
    def info(self) -> AdapterInfo:
        return AdapterInfo(
            self.adapter_id,
            self.version,
            self.license_name,
            self.capabilities,
            self.verified,
        )

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

        command = tuple(self.command) + (str(output),)
        try:
            completed = subprocess.run(
                command,
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
                "canonical_source_hash": request.canonical_source_hash,
                "output_sha256": digest,
                "exit_code": completed.returncode,
            },
        )
