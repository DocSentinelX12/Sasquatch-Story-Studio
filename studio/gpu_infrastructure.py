"""Truthful NVIDIA GPU and CUDA host observation.

This module only reports hardware and software evidence actually observed on a
worker. It never creates synthetic capacity and it has no dependency on a GPU
vendor Python package, so the control plane can inspect a worker before heavy
CUDA libraries are installed.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Callable, Sequence

from .gpu_topology import GpuTopologyEvidence, parse_nvidia_smi_topology
from .nccl_evidence import NCCLTestEvidence


class GpuTelemetryStatus(StrEnum):
    OBSERVED = "observed"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class TelemetryValue:
    status: str
    value: object | None
    source: str
    observed_at: int
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in {
            GpuTelemetryStatus.OBSERVED,
            GpuTelemetryStatus.UNSUPPORTED,
            GpuTelemetryStatus.UNAVAILABLE,
            GpuTelemetryStatus.ERROR,
        }:
            raise ValueError(f"invalid GPU telemetry status: {self.status}")
        if not self.source.strip():
            raise ValueError("telemetry source is required")
        if self.observed_at < 0:
            raise ValueError("telemetry timestamp cannot be negative")
        if self.status != GpuTelemetryStatus.OBSERVED and self.value is not None:
            raise ValueError("non-observed telemetry cannot contain a value")


@dataclass(frozen=True)
class GpuTelemetryEvidence:
    source: str
    collected_at: int
    collector: str
    fields: tuple[tuple[str, TelemetryValue], ...] | dict[str, TelemetryValue]

    def __post_init__(self) -> None:
        if not self.source.strip() or not self.collector.strip():
            raise ValueError("telemetry source and collector are required")
        if self.collected_at < 0:
            raise ValueError("telemetry collection timestamp cannot be negative")
        normalized = tuple(sorted(dict(self.fields).items()))
        if len({name for name, _ in normalized}) != len(normalized):
            raise ValueError("telemetry field names must be unique")
        object.__setattr__(self, "fields", normalized)

    def field(self, name: str) -> TelemetryValue:
        for field_name, value in self.fields:
            if field_name == name:
                return value
        raise KeyError(f"unknown GPU telemetry field: {name}")

    def is_fresh(self, *, now: int, max_age_seconds: int) -> bool:
        if now < self.collected_at or max_age_seconds < 0:
            return False
        return now - self.collected_at <= max_age_seconds


@dataclass(frozen=True)
class GpuDeviceObservation:
    index: int
    uuid: str
    name: str
    memory_total_mib: int
    memory_used_mib: int
    pci_bus_id: str
    compute_capability: str
    telemetry: GpuTelemetryEvidence | None = None

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
    topology_evidence: GpuTopologyEvidence | None = None

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("worker_id is required")
        if not self.driver_version.strip() or not self.cuda_supported_version.strip():
            raise ValueError("driver and CUDA versions must be observed")
        if len({gpu.uuid for gpu in self.gpus}) != len(self.gpus):
            raise ValueError("GPU UUIDs must be unique")
        if self.dcgm_available and not (self.dcgm_version or "").strip():
            raise ValueError("DCGM availability requires an observed version")
        if self.topology_evidence is not None:
            observed = tuple(gpu.uuid for gpu in sorted(self.gpus, key=lambda item: item.index))
            if self.topology_evidence.gpu_uuids != observed:
                raise ValueError("topology evidence must match the observed GPU inventory")

    @property
    def gpu_count(self) -> int:
        return len(self.gpus)

    def canonical_json(self) -> str:
        payload = asdict(self)
        payload["gpus"] = [asdict(gpu) for gpu in self.gpus]
        if self.nccl_evidence is not None:
            payload["nccl_evidence"]["command"] = list(self.nccl_evidence.command)
            payload["nccl_evidence"]["gpu_uuids"] = list(self.nccl_evidence.gpu_uuids)
        if self.topology_evidence is not None:
            payload["topology_evidence"]["gpu_uuids"] = list(self.topology_evidence.gpu_uuids)
            payload["topology_evidence"]["gpu_matrix"] = [list(row) for row in self.topology_evidence.gpu_matrix]
            payload["topology_evidence"]["cpu_affinity"] = [list(item) for item in self.topology_evidence.cpu_affinity]
            payload["topology_evidence"]["nic_paths"] = [list(item) for item in self.topology_evidence.nic_paths]
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


_TELEMETRY_FIELDS = (
    "temperature_c",
    "power_usage_w",
    "power_state",
    "utilization_percent",
    "memory_utilization_percent",
    "ecc_mode",
    "ecc_errors",
    "mig_mode",
    "nvlink_state",
    "pcie_link",
    "xid_errors",
)


class _PynvmlProvider:
    def __init__(self, module):
        self.module = module
        self.handles: dict[int, object] = {}

    def initialize(self) -> None:
        self.module.nvmlInit()

    def shutdown(self) -> None:
        self.module.nvmlShutdown()

    def driver_version(self) -> str:
        return self.module.nvmlSystemGetDriverVersion().decode()

    def cuda_version(self) -> str:
        value = self.module.nvmlSystemGetCudaDriverVersion()
        major, remainder = divmod(int(value), 1000)
        minor = remainder // 10
        return f"{major}.{minor}"

    def devices(self) -> tuple[dict[str, object], ...]:
        result = []
        for index in range(self.module.nvmlDeviceGetCount()):
            handle = self.module.nvmlDeviceGetHandleByIndex(index)
            self.handles[index] = handle
            memory = self.module.nvmlDeviceGetMemoryInfo(handle)
            pci = self.module.nvmlDeviceGetPciInfo(handle)
            result.append(
                {
                    "index": index,
                    "uuid": self.module.nvmlDeviceGetUUID(handle).decode(),
                    "name": self.module.nvmlDeviceGetName(handle).decode(),
                    "memory_total_mib": int(memory.total // (1024 * 1024)),
                    "memory_used_mib": int(memory.used // (1024 * 1024)),
                    "pci_bus_id": pci.busId.decode(),
                    "compute_capability": self._compute_capability(handle),
                }
            )
        return tuple(result)

    def _compute_capability(self, handle) -> str:
        major, minor = self.module.nvmlDeviceGetCudaComputeCapability(handle)
        return f"{major}.{minor}"

    def field(self, index: int, name: str):
        handle = self.handles[index]
        m = self.module
        if name == "temperature_c":
            return int(m.nvmlDeviceGetTemperature(handle, m.NVML_TEMPERATURE_GPU))
        if name == "power_usage_w":
            return float(m.nvmlDeviceGetPowerUsage(handle)) / 1000.0
        if name == "power_state":
            return f"P{m.nvmlDeviceGetPowerState(handle)}"
        if name == "utilization_percent":
            return int(m.nvmlDeviceGetUtilizationRates(handle).gpu)
        if name == "memory_utilization_percent":
            return int(m.nvmlDeviceGetUtilizationRates(handle).memory)
        if name == "ecc_mode":
            current, _ = m.nvmlDeviceGetEccMode(handle)
            return "enabled" if current else "disabled"
        if name == "ecc_errors":
            return {
                "volatile": int(m.nvmlDeviceGetTotalEccErrors(handle, m.NVML_MEMORY_ERROR_TYPE_UNCORRECTED, m.NVML_VOLATILE_ECC)),
                "aggregate": int(m.nvmlDeviceGetTotalEccErrors(handle, m.NVML_MEMORY_ERROR_TYPE_UNCORRECTED, m.NVML_AGGREGATE_ECC)),
            }
        if name == "mig_mode":
            getter = getattr(m, "nvmlDeviceGetMigMode", None)
            if getter is None:
                raise NotImplementedError("NVML does not expose MIG mode")
            current, _ = getter(handle)
            return "enabled" if current else "disabled"
        if name == "nvlink_state":
            getter = getattr(m, "nvmlDeviceGetNvLinkState", None)
            if getter is None:
                raise NotImplementedError("NVML does not expose NVLink state")
            states = []
            for link in range(0, 32):
                try:
                    states.append(bool(getter(handle, link)))
                except Exception:
                    break
            return "up" if any(states) else "down"
        if name == "pcie_link":
            generation = m.nvmlDeviceGetMaxPcieLinkGeneration(handle)
            width = m.nvmlDeviceGetMaxPcieLinkWidth(handle)
            return {"generation": int(generation), "width": int(width)}
        if name == "xid_errors":
            raise NotImplementedError("NVML does not provide a portable XID history API")
        raise KeyError(name)


def _load_nvml_provider():
    try:
        module = importlib.import_module("pynvml")
    except (ImportError, ModuleNotFoundError):
        return None
    return _PynvmlProvider(module)


def _telemetry_value(
    provider,
    runner: Runner,
    index: int,
    name: str,
    now: int,
) -> TelemetryValue:
    if provider is not None:
        try:
            return TelemetryValue(
                GpuTelemetryStatus.OBSERVED,
                provider.field(index, name),
                "nvml",
                now,
            )
        except NotImplementedError as exc:
            status = GpuTelemetryStatus.UNSUPPORTED
            detail = str(exc)
        except Exception as exc:
            status = GpuTelemetryStatus.ERROR
            detail = str(exc)
        else:
            raise AssertionError("unreachable")

        try:
            value = _run_nvidia_smi_field(runner, index, name)
        except Exception as fallback_exc:
            if status == GpuTelemetryStatus.UNSUPPORTED:
                return TelemetryValue(status, None, "nvml", now, detail)
            return TelemetryValue(GpuTelemetryStatus.ERROR, None, "nvml", now, f"{detail}; fallback failed: {fallback_exc}")
        return TelemetryValue(GpuTelemetryStatus.OBSERVED, value, "nvidia-smi", now, detail)

    try:
        value = _run_nvidia_smi_field(runner, index, name)
    except NotImplementedError as exc:
        return TelemetryValue(GpuTelemetryStatus.UNSUPPORTED, None, "nvidia-smi", now, str(exc))
    except Exception as exc:
        return TelemetryValue(GpuTelemetryStatus.UNAVAILABLE, None, "nvidia-smi", now, str(exc))
    return TelemetryValue(GpuTelemetryStatus.OBSERVED, value, "nvidia-smi", now)


def _run_nvidia_smi_field(runner: Runner, index: int, name: str):
    queries = {
        "power_usage_w": "power.draw",
        "temperature_c": "temperature.gpu",
        "power_state": "pstate",
        "utilization_percent": "utilization.gpu",
        "memory_utilization_percent": "utilization.memory",
        "ecc_mode": "ecc.mode.current",
        "mig_mode": "mig.mode.current",
    }
    query = queries.get(name)
    if query is None:
        raise NotImplementedError(f"nvidia-smi fallback does not expose {name}")
    output = _run_text(
        runner,
        (
            "nvidia-smi",
            f"--query-gpu=index,{query}",
            "--format=csv,noheader,nounits",
        ),
    )
    for line in output.splitlines():
        fields = [part.strip() for part in line.split(",")]
        if len(fields) != 2 or int(fields[0]) != index:
            continue
        value = fields[1]
        if name in {"temperature_c", "utilization_percent", "memory_utilization_percent"}:
            return int(value)
        if name == "power_usage_w":
            return float(value)
        return value
    raise RuntimeError(f"nvidia-smi returned no telemetry for GPU {index}: {name}")


def _build_nvml_observation(worker_id: str, provider, now: int) -> tuple[str, str, tuple[GpuDeviceObservation, ...]]:
    provider.initialize()
    try:
        driver = provider.driver_version()
        cuda = provider.cuda_version()
        devices = []
        for device in provider.devices():
            fields = tuple(
                (name, _telemetry_value(provider, _default_runner, int(device["index"]), name, now))
                for name in _TELEMETRY_FIELDS
            )
            telemetry = GpuTelemetryEvidence("nvml", now, "pynvml", fields)
            devices.append(GpuDeviceObservation(**device, telemetry=telemetry))
        return driver, cuda, tuple(devices)
    finally:
        provider.shutdown()


def probe_nvidia_host(
    worker_id: str,
    runner: Runner = _default_runner,
    *,
    nvml_loader: Callable[[], object | None] | None = None,
) -> GpuHostObservation:
    """Probe a real NVIDIA host using NVML first and explicit nvidia-smi fallback."""
    now = int(time.time())
    provider = (nvml_loader or _load_nvml_provider)()
    if provider is not None:
        try:
            provider.initialize()
            driver_version = provider.driver_version()
            cuda_version = provider.cuda_version()
            raw_devices = provider.devices()
            gpus = []
            for device in raw_devices:
                index = int(device["index"])
                fields = tuple(
                    (name, _telemetry_value(provider, runner, index, name, now))
                    for name in _TELEMETRY_FIELDS
                )
                gpus.append(
                    GpuDeviceObservation(
                        index=index,
                        uuid=str(device["uuid"]),
                        name=str(device["name"]),
                        memory_total_mib=int(device["memory_total_mib"]),
                        memory_used_mib=int(device["memory_used_mib"]),
                        pci_bus_id=str(device["pci_bus_id"]),
                        compute_capability=str(device["compute_capability"]),
                        telemetry=GpuTelemetryEvidence("nvml", now, "pynvml", fields),
                    )
                )
            if not gpus:
                raise RuntimeError("NVML succeeded but reported no physical GPUs")
            provider.shutdown()
        except Exception:
            try:
                provider.shutdown()
            except Exception:
                pass
            provider = None

    if provider is None:
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
        raw_gpus = parse_nvidia_smi_gpu_csv(gpu_csv)
        if not raw_gpus:
            raise RuntimeError("nvidia-smi succeeded but reported no physical GPUs")
        gpus = []
        for gpu in raw_gpus:
            fields = tuple(
                (name, _telemetry_value(None, runner, gpu.index, name, now))
                for name in _TELEMETRY_FIELDS
            )
            gpus.append(
                GpuDeviceObservation(
                    gpu.index,
                    gpu.uuid,
                    gpu.name,
                    gpu.memory_total_mib,
                    gpu.memory_used_mib,
                    gpu.pci_bus_id,
                    gpu.compute_capability,
                    telemetry=GpuTelemetryEvidence("nvidia-smi", now, "nvidia-smi", fields),
                )
            )

    topology: str | None = None
    topology_evidence: GpuTopologyEvidence | None = None
    if shutil.which("nvidia-smi") or provider is not None:
        try:
            topology = _run_text(runner, ("nvidia-smi", "topo", "-m"))
            topology_evidence = parse_nvidia_smi_topology(topology, {gpu.index: gpu.uuid for gpu in gpus})
        except Exception:
            topology = None
            topology_evidence = None

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
        gpus=tuple(gpus),
        topology_text=topology,
        dcgm_available=dcgm_available,
        dcgm_version=dcgm_version,
        health_json=health_json,
        topology_evidence=topology_evidence,
    )
