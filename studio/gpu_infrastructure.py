"""Truthful NVIDIA GPU and CUDA host observation.

This module only reports hardware and software evidence actually observed on a
worker. It never creates synthetic capacity and it has no dependency on a GPU
vendor Python package, so the control plane can inspect a worker before heavy
CUDA libraries are installed.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Callable, Sequence

from .nccl_evidence import NCCLTestEvidence


@dataclass(frozen=True)
class GpuDeviceObservation:
    index: int
    uuid: str
    name: str
    memory_total_mib: int
    memory_used_mib: int
    pci_bus_id: str
    compute_capability: str

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("GPU index cannot be negative")
        for field_name in ("uuid", "name", "pci_bus_id", "compute_capability"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} is required")
        if self.memory_total_mib < 0 or self.memory_used_mib < 0:
            raise ValueError("GPU memory values cannot be negative")
        if self.memory_used_mib > self.memory_total_mib:
            raise ValueError("GPU used memory cannot exceed total memory")


@dataclass(frozen=True)
class GpuHostObservation:
    worker_id: str
    driver_version: str
    cuda_supported_version: str
    gpus: tuple[GpuDeviceObservation, ...]
    topology_text: str | None
    dcgm_available: bool
    dcgm_version: str | None
    health_json: str | None
    nccl_evidence: NCCLTestEvidence | None = None

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("worker_id is required")
        if not self.driver_version.strip() or not self.cuda_supported_version.strip():
            raise ValueError("driver and CUDA versions must be observed")
        if len({gpu.uuid for gpu in self.gpus}) != len(self.gpus):
            raise ValueError("GPU UUIDs must be unique")
        if self.dcgm_available and not (self.dcgm_version or "").strip():
            raise ValueError("DCGM availability requires an observed version")

    @property
    def gpu_count(self) -> int:
        return len(self.gpus)

    def canonical_json(self) -> str:
        payload = asdict(self)
        payload["gpus"] = [asdict(gpu) for gpu in self.gpus]
        if self.nccl_evidence is not None:
            payload["nccl_evidence"]["command"] = list(self.nccl_evidence.command)
            payload["nccl_evidence"]["gpu_uuids"] = list(self.nccl_evidence.gpu_uuids)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _split_csv_line(line: str) -> list[str]:
    return [part.strip() for part in line.split(",")]


def parse_nvidia_smi_gpu_csv(output: str) -> tuple[GpuDeviceObservation, ...]:
    """Parse the exact no-header CSV shape requested by the probe."""
    devices: list[GpuDeviceObservation] = []
    for line_number, raw_line in enumerate(output.splitlines(), start=1):
        if not raw_line.strip():
            continue
        fields = _split_csv_line(raw_line)
        if len(fields) != 7:
            raise ValueError(f"nvidia-smi GPU query line {line_number} has {len(fields)} fields, expected 7")
        try:
            index = int(fields[0])
            total = int(fields[3])
            used = int(fields[4])
        except ValueError as exc:
            raise ValueError(f"invalid nvidia-smi numeric field on line {line_number}") from exc
        devices.append(GpuDeviceObservation(index, fields[1], fields[2], total, used, fields[5], fields[6]))
    return tuple(devices)


_VERSION_RE = re.compile(r"Driver Version:\s*([^\s]+).*?CUDA Version:\s*([^\s]+)", re.DOTALL)


def parse_nvidia_smi_header(output: str) -> tuple[str, str]:
    match = _VERSION_RE.search(output)
    if not match:
        raise ValueError("nvidia-smi output did not expose both Driver Version and CUDA Version")
    return match.group(1), match.group(2)


def classify_dcgm_health(output: str | None) -> str:
    """Classify only the explicit overall DCGM health result."""
    if not output:
        return "unknown"
    for line in output.splitlines():
        normalized = " ".join(line.strip().split()).lower()
        if "overall health" not in normalized:
            continue
        if "failure" in normalized:
            return "failure"
        if "warning" in normalized:
            return "warning"
        if "healthy" in normalized:
            return "healthy"
    return "unknown"


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)


def _run_text(runner: Runner, command: Sequence[str]) -> str:
    result = runner(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}{': ' + detail if detail else ''}")
    return result.stdout


def probe_nvidia_host(worker_id: str, runner: Runner = _default_runner) -> GpuHostObservation:
    """Probe a real NVIDIA host using vendor-supported command-line evidence."""
    if not shutil.which("nvidia-smi"):
        raise RuntimeError("nvidia-smi is not installed or not available on PATH")

    header = _run_text(runner, ("nvidia-smi",))
    driver_version, cuda_version = parse_nvidia_smi_header(header)
    gpu_csv = _run_text(
        runner,
        (
            "nvidia-smi",
            "--query-gpu=index,uuid,name,memory.total,memory.used,pci.bus_id,compute_cap",
            "--format=csv,noheader,nounits",
        ),
    )
    gpus = parse_nvidia_smi_gpu_csv(gpu_csv)
    if not gpus:
        raise RuntimeError("nvidia-smi succeeded but reported no physical GPUs")

    topology = _run_text(runner, ("nvidia-smi", "topo", "-m"))

    dcgm_available = shutil.which("dcgmi") is not None
    dcgm_version: str | None = None
    health_json: str | None = None
    if dcgm_available:
        try:
            dcgm_version = _run_text(runner, ("dcgmi", "--version")).strip()
        except RuntimeError:
            dcgm_available = False
        if dcgm_available:
            try:
                health_json = _run_text(runner, ("dcgmi", "health", "--check", "--group", "g", "--json")).strip()
            except RuntimeError:
                health_json = None

    return GpuHostObservation(
        worker_id=worker_id,
        driver_version=driver_version,
        cuda_supported_version=cuda_version,
        gpus=gpus,
        topology_text=topology,
        dcgm_available=dcgm_available,
        dcgm_version=dcgm_version,
        health_json=health_json,
    )
