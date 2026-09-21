"""Truthful NVIDIA GPU and CUDA host observation.

Physical observations are evidence, not inferred capability. NVML is preferred
when it is installed and usable; nvidia-smi is an explicit fallback. Every
telemetry field carries its own status, source, and collection timestamp so
missing or stale data can never silently become a verified capability.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Callable, Sequence

from .gpu_topology import GpuTopologyEvidence, parse_nvidia_smi_topology
from .nccl_evidence import NCCLTestEvidence


class TelemetryStatus(StrEnum):
    OBSERVED = "observed"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class TelemetryEvidence:
    status: TelemetryStatus
    value: Any = None
    source: str = ""
    collected_at: int = 0
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("telemetry source is required")
        if self.collected_at < 0:
            raise ValueError("telemetry collection time cannot be negative")
        if self.status is TelemetryStatus.OBSERVED:
            if self.value is None:
                raise ValueError("observed telemetry requires a value")
            if self.error is not None:
                raise ValueError("observed telemetry cannot contain an error")
        elif self.value is not None:
            raise ValueError("non-observed telemetry cannot contain a value")
        if self.status is TelemetryStatus.ERROR and not (self.error or "").strip():
            raise ValueError("error telemetry requires an error description")


def _observed(value: Any, source: str, collected_at: int) -> TelemetryEvidence:
    return TelemetryEvidence(TelemetryStatus.OBSERVED, value, source, collected_at)


def _unavailable(source: str, collected_at: int, status: TelemetryStatus = TelemetryStatus.UNAVAILABLE, error: str | None = None) -> TelemetryEvidence:
    return TelemetryEvidence(status, None, source, collected_at, error)


@dataclass(frozen=True)
class GpuTelemetryObservation:
    temperature_c: TelemetryEvidence
    power_usage_w: TelemetryEvidence
    power_limit_w: TelemetryEvidence
    utilization_percent: TelemetryEvidence
    memory_utilization_percent: TelemetryEvidence
    ecc_errors: TelemetryEvidence
    mig_mode: TelemetryEvidence
    nvlink_state: TelemetryEvidence
    pcie_link_generation: TelemetryEvidence
    pcie_link_width: TelemetryEvidence
    pcie_tx_kb_s: TelemetryEvidence
    pcie_rx_kb_s: TelemetryEvidence
    xid_errors: TelemetryEvidence
    dcgm_health: TelemetryEvidence
    collector_identity: str

    def __post_init__(self) -> None:
        if not self.collector_identity.strip():
            raise ValueError("collector identity is required")

    @classmethod
    def unavailable(cls, source: str = "legacy_observation", collected_at: int = 0) -> "GpuTelemetryObservation":
        fields = {
            name: _unavailable(source, collected_at)
            for name in (
                "temperature_c",
                "power_usage_w",
                "power_limit_w",
                "utilization_percent",
                "memory_utilization_percent",
                "ecc_errors",
                "mig_mode",
                "nvlink_state",
                "pcie_link_generation",
                "pcie_link_width",
                "pcie_tx_kb_s",
                "pcie_rx_kb_s",
                "xid_errors",
                "dcgm_health",
            )
        }
        return cls(**fields, collector_identity=source)

    def is_fresh(self, now: int, max_age_seconds: int, fields: Sequence[str] | None = None) -> bool:
        if now < 0 or max_age_seconds < 0:
            raise ValueError("freshness arguments cannot be negative")
        names = tuple(fields) if fields is not None else tuple(self.__dataclass_fields__)
        names = tuple(name for name in names if name != "collector_identity")
        for name in names:
            evidence = getattr(self, name)
            if evidence.status is not TelemetryStatus.OBSERVED:
                return False
            if now - evidence.collected_at < 0 or now - evidence.collected_at > max_age_seconds:
                return False
        return True


@dataclass(frozen=True)
class GpuDeviceObservation:
    index: int
    uuid: str
    name: str
    memory_total_mib: int
    memory_used_mib: int
    pci_bus_id: str
    compute_capability: str
    telemetry: GpuTelemetryObservation = field(default_factory=GpuTelemetryObservation.unavailable)

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
    observed_at: int = 0
    collector_identity: str = "legacy_observation"

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("worker_id is required")
        if not self.driver_version.strip() or not self.cuda_supported_version.strip():
            raise ValueError("driver and CUDA versions must be observed")
        if len({gpu.uuid for gpu in self.gpus}) != len(self.gpus):
            raise ValueError("GPU UUIDs must be unique")
        if self.observed_at < 0:
            raise ValueError("observation time cannot be negative")
        if not self.collector_identity.strip():
            raise ValueError("collector identity is required")
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


def _parse_nvidia_smi_telemetry_csv(output: str, collected_at: int) -> dict[int, dict[str, TelemetryEvidence]]:
    result: dict[int, dict[str, TelemetryEvidence]] = {}
    fields = (
        "index",
        "temperature_c",
        "power_usage_w",
        "power_limit_w",
        "utilization_percent",
        "memory_utilization_percent",
        "ecc_errors",
        "mig_mode",
        "pcie_link_generation",
        "pcie_link_width",
        "pcie_tx_kb_s",
        "pcie_rx_kb_s",
    )
    for line_number, raw_line in enumerate(output.splitlines(), start=1):
        if not raw_line.strip():
            continue
        values = _split_csv_line(raw_line)
        if len(values) != len(fields):
            raise ValueError(f"nvidia-smi telemetry line {line_number} has {len(values)} fields, expected {len(fields)}")
        index = int(values[0])
        parsed: dict[str, TelemetryEvidence] = {}
        numeric_fields = {
            "temperature_c": float,
            "power_usage_w": float,
            "power_limit_w": float,
            "utilization_percent": float,
            "memory_utilization_percent": float,
            "ecc_errors": int,
            "pcie_link_generation": int,
            "pcie_link_width": int,
            "pcie_tx_kb_s": float,
            "pcie_rx_kb_s": float,
        }
        for name, parser in numeric_fields.items():
            raw = values[fields.index(name)]
            if raw in {"", "N/A", "[Not Supported]"}:
                parsed[name] = _unavailable("nvidia-smi", collected_at, TelemetryStatus.UNSUPPORTED if raw == "[Not Supported]" else TelemetryStatus.UNAVAILABLE)
            else:
                parsed[name] = _observed(parser(raw), "nvidia-smi", collected_at)
        mig = values[fields.index("mig_mode")]
        parsed["mig_mode"] = _unavailable("nvidia-smi", collected_at, TelemetryStatus.UNSUPPORTED if mig == "[Not Supported]" else TelemetryStatus.UNAVAILABLE) if mig in {"", "N/A", "[Not Supported]"} else _observed(mig, "nvidia-smi", collected_at)
        result[index] = parsed
    return result


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


def _load_nvml():
    try:
        return importlib.import_module("pynvml")
    except (ImportError, ModuleNotFoundError):
        return None


def _nvml_optional_call(nvml: Any, name: str, *args: Any) -> Any:
    function = getattr(nvml, name, None)
    if function is None:
        raise NotImplementedError(name)
    return function(*args)


def _decode_nvml_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    return str(value)


def _probe_nvml(worker_id: str, nvml: Any, collected_at: int) -> GpuHostObservation:
    nvml.nvmlInit()
    try:
        count = int(_nvml_optional_call(nvml, "nvmlDeviceGetCount"))
        if count <= 0:
            raise RuntimeError("NVML reported no physical GPUs")
        gpus: list[GpuDeviceObservation] = []
        for index in range(count):
            handle = nvml.nvmlDeviceGetHandleByIndex(index)
            uuid = _decode_nvml_text(nvml.nvmlDeviceGetUUID(handle))
            name = _decode_nvml_text(nvml.nvmlDeviceGetName(handle))
            memory = nvml.nvmlDeviceGetMemoryInfo(handle)
            pci = nvml.nvmlDeviceGetPciInfo(handle)
            bus_id = pci.busId.decode() if isinstance(pci.busId, bytes) else str(pci.busId)
            compute = nvml.nvmlDeviceGetCudaComputeCapability(handle)
            compute_capability = f"{compute[0]}.{compute[1]}"
            telemetry_kwargs: dict[str, TelemetryEvidence] = {}
            def optional(name: str, value_factory: Callable[[], Any], transform: Callable[[Any], Any] | None = None) -> None:
                try:
                    value = value_factory()
                    telemetry_kwargs[name] = _observed(transform(value) if transform else value, "nvml", collected_at)
                except Exception as exc:
                    status = TelemetryStatus.UNSUPPORTED if isinstance(exc, (AttributeError, NotImplementedError)) else TelemetryStatus.ERROR
                    telemetry_kwargs[name] = _unavailable("nvml", collected_at, status, str(exc) if status is TelemetryStatus.ERROR else None)
            optional("temperature_c", lambda: nvml.nvmlDeviceGetTemperature(handle, getattr(nvml, "NVML_TEMPERATURE_GPU", 0)))
            optional("power_usage_w", lambda: nvml.nvmlDeviceGetPowerUsage(handle), lambda value: float(value) / 1000.0)
            optional("power_limit_w", lambda: nvml.nvmlDeviceGetEnforcedPowerLimit(handle), lambda value: float(value) / 1000.0)
            optional("utilization_percent", lambda: nvml.nvmlDeviceGetUtilizationRates(handle).gpu)
            optional("memory_utilization_percent", lambda: nvml.nvmlDeviceGetUtilizationRates(handle).memory)
            optional("ecc_errors", lambda: nvml.nvmlDeviceGetTotalEccErrors(handle, 0, 0))
            optional("mig_mode", lambda: nvml.nvmlDeviceGetMigMode(handle)[0])
            optional("pcie_link_generation", lambda: nvml.nvmlDeviceGetPcieLinkGeneration(handle))
            optional("pcie_link_width", lambda: nvml.nvmlDeviceGetPcieLinkWidth(handle))
            optional("pcie_tx_kb_s", lambda: nvml.nvmlDeviceGetPcieThroughput(handle, 0))
            optional("pcie_rx_kb_s", lambda: nvml.nvmlDeviceGetPcieThroughput(handle, 1))
            optional("nvlink_state", lambda: any(bool(nvml.nvmlDeviceGetNvLinkState(handle, link)) for link in range(16)))
            telemetry = GpuTelemetryObservation(
                **telemetry_kwargs,
                xid_errors=_unavailable("nvml", collected_at, TelemetryStatus.UNSUPPORTED),
                dcgm_health=_unavailable("nvml", collected_at, TelemetryStatus.UNAVAILABLE),
                collector_identity="nvml",
            )
            gpus.append(GpuDeviceObservation(index, uuid, name, int(memory.total / 1024**2), int(memory.used / 1024**2), bus_id, compute_capability, telemetry))
        driver_raw = _nvml_optional_call(nvml, "nvmlSystemGetDriverVersion")
        cuda_raw = _nvml_optional_call(nvml, "nvmlSystemGetCudaDriverVersion_v2")
        driver_version = driver_raw.decode() if isinstance(driver_raw, bytes) else str(driver_raw)
        cuda_version_number = int(cuda_raw)
        cuda_version = f"{cuda_version_number // 1000}.{(cuda_version_number % 1000) // 10}"
        return GpuHostObservation(
            worker_id=worker_id,
            driver_version=driver_version,
            cuda_supported_version=cuda_version,
            gpus=tuple(gpus),
            topology_text=None,
            dcgm_available=False,
            dcgm_version=None,
            health_json=None,
            topology_evidence=None,
            observed_at=collected_at,
            collector_identity="nvml",
        )
    finally:
        nvml.nvmlShutdown()


def _probe_nvidia_smi(worker_id: str, runner: Runner, collected_at: int) -> GpuHostObservation:
    if not shutil.which("nvidia-smi"):
        raise RuntimeError("nvidia-smi is not installed or not available on PATH")
    header = _run_text(runner, ("nvidia-smi",))
    driver_version, cuda_version = parse_nvidia_smi_header(header)
    gpu_csv = _run_text(
        runner,
        ("nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.used,pci.bus_id,compute_cap", "--format=csv,noheader,nounits"),
    )
    base_gpus = parse_nvidia_smi_gpu_csv(gpu_csv)
    if not base_gpus:
        raise RuntimeError("nvidia-smi succeeded but reported no physical GPUs")
    try:
        telemetry_csv = _run_text(
            runner,
            (
                "nvidia-smi",
                "--query-gpu=index,temperature.gpu,power.draw,power.limit,utilization.gpu,utilization.memory,ecc.errors.uncorrected.aggregate,mig.mode.current,pcie.link.gen.current,pcie.link.width.current,pcie.tx_util,pcie.rx_util",
                "--format=csv,noheader,nounits",
            ),
        )
        telemetry_by_index = _parse_nvidia_smi_telemetry_csv(telemetry_csv, collected_at)
    except (RuntimeError, ValueError):
        telemetry_by_index = {}
    topology = _run_text(runner, ("nvidia-smi", "topo", "-m"))
    topology_evidence = parse_nvidia_smi_topology(topology, {gpu.index: gpu.uuid for gpu in base_gpus})
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
    gpus: list[GpuDeviceObservation] = []
    for gpu in base_gpus:
        values = telemetry_by_index.get(gpu.index, {})
        defaults = GpuTelemetryObservation.unavailable("nvidia-smi", collected_at)
        telemetry = GpuTelemetryObservation(
            **{
                field_name: values.get(field_name, getattr(defaults, field_name))
                for field_name in (
                    "temperature_c", "power_usage_w", "power_limit_w", "utilization_percent",
                    "memory_utilization_percent", "ecc_errors", "mig_mode", "nvlink_state",
                    "pcie_link_generation", "pcie_link_width", "pcie_tx_kb_s", "pcie_rx_kb_s",
                )
            },
            xid_errors=_unavailable("nvidia-smi", collected_at, TelemetryStatus.UNSUPPORTED),
            dcgm_health=_observed(classify_dcgm_health(health_json), "dcgm", collected_at) if health_json else _unavailable("dcgm", collected_at),
            collector_identity="nvidia-smi",
        )
        gpus.append(GpuDeviceObservation(gpu.index, gpu.uuid, gpu.name, gpu.memory_total_mib, gpu.memory_used_mib, gpu.pci_bus_id, gpu.compute_capability, telemetry))
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
        observed_at=collected_at,
        collector_identity="nvidia-smi",
    )


def probe_nvidia_host(
    worker_id: str,
    runner: Runner = _default_runner,
    now: int | None = None,
    nvml_loader: Callable[[], Any | None] = _load_nvml,
) -> GpuHostObservation:
    """Probe one physical NVIDIA host, preferring NVML and explicitly falling back."""
    collected_at = int(time.time()) if now is None else now
    if collected_at < 0:
        raise ValueError("observation time cannot be negative")
    nvml = nvml_loader()
    if nvml is not None:
        try:
            return _probe_nvml(worker_id, nvml, collected_at)
        except (AttributeError, ImportError, NotImplementedError, RuntimeError, TypeError, ValueError):
            pass
    return _probe_nvidia_smi(worker_id, runner, collected_at)
