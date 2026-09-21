from __future__ import annotations

import json

import pytest

from studio.gpu_infrastructure import (
    GpuDeviceObservation,
    GpuHostObservation,
    GpuTelemetryEvidence,
    GpuTelemetryStatus,
    TelemetryValue,
    parse_nvidia_smi_gpu_csv,
    parse_nvidia_smi_header,
    probe_nvidia_host,
)


class FakeNvml:
    """Deterministic NVML-shaped provider used only at the collector boundary."""

    def __init__(self, *, temperature: int = 61, fail_power: bool = False):
        self.fail_power = fail_power
        self.calls: list[str] = []

    def initialize(self):
        self.calls.append("initialize")

    def shutdown(self):
        self.calls.append("shutdown")

    def driver_version(self):
        self.calls.append("driver_version")
        return "580.95.05"

    def cuda_version(self):
        self.calls.append("cuda_version")
        return "13.0"

    def devices(self):
        self.calls.append("devices")
        return (
            {
                "index": 0,
                "uuid": "GPU-aaa",
                "name": "NVIDIA Test GPU",
                "memory_total_mib": 81920,
                "memory_used_mib": 1024,
                "pci_bus_id": "00000000:17:00.0",
                "compute_capability": "10.0",
            },
        )

    def field(self, index: int, name: str):
        self.calls.append(f"field:{index}:{name}")
        values = {
            "temperature_c": 61,
            "power_usage_w": 225.5,
            "power_state": "P0",
            "utilization_percent": 47,
            "memory_utilization_percent": 12,
            "ecc_mode": "enabled",
            "ecc_errors": {"volatile": 0, "aggregate": 0},
            "mig_mode": "disabled",
            "nvlink_state": "up",
            "pcie_link": {"generation": 5, "width": 16},
            "xid_errors": (),
        }
        if name == "power_usage_w" and self.fail_power:
            raise RuntimeError("NVML power query failed")
        return values[name]

    def dcgm_evidence(self):
        self.calls.append("dcgm_evidence")
        return None


def _smi_runner(command):
    class Result:
        returncode = 0
        stderr = ""
        stdout = ""

    if tuple(command) == ("nvidia-smi",):
        Result.stdout = "NVIDIA-SMI 580.95.05    Driver Version: 580.95.05    CUDA Version: 13.0"
    elif command[1:] == ("--query-gpu=index,uuid,name,memory.total,memory.used,pci.bus_id,compute_cap", "--format=csv,noheader,nounits"):
        Result.stdout = "0, GPU-aaa, NVIDIA Test GPU, 81920, 1024, 00000000:17:00.0, 10.0\n"
    elif tuple(command) == ("nvidia-smi", "topo", "-m"):
        Result.stdout = "GPU0\tX\n"
    else:
        Result.returncode = 1
        Result.stderr = "unexpected command"
    return Result()


def test_nvml_is_preferred_and_supplies_machine_readable_telemetry():
    nvml = FakeNvml()
    observation = probe_nvidia_host("worker-a", runner=_smi_runner, nvml_loader=lambda: nvml)

    assert nvml.calls[:3] == ["initialize", "driver_version", "cuda_version"]
    telemetry = observation.gpus[0].telemetry
    assert telemetry.source == "nvml"
    assert telemetry.field("temperature_c").value == 61
    assert telemetry.field("power_usage_w").value == 225.5
    assert telemetry.field("utilization_percent").value == 47
    assert telemetry.field("memory_utilization_percent").value == 12
    assert telemetry.field("ecc_mode").value == "enabled"
    assert telemetry.field("mig_mode").value == "disabled"
    assert telemetry.field("nvlink_state").value == "up"
    assert telemetry.field("pcie_link").value == {"generation": 5, "width": 16}
    assert telemetry.field("xid_errors").value == ()


def test_nvml_field_failure_uses_explicit_nvidia_smi_fallback_provenance():
    nvml = FakeNvml(fail_power=True)

    def fallback_runner(command):
        result = _smi_runner(command)
        if tuple(command) == ("nvidia-smi", "--query-gpu=index,power.draw", "--format=csv,noheader,nounits"):
            result.stdout = "0, 225.5\n"
        return result

    observation = probe_nvidia_host("worker-a", runner=fallback_runner, nvml_loader=lambda: nvml)
    power = observation.gpus[0].telemetry.field("power_usage_w")

    assert power.value == 225.5
    assert power.source == "nvidia-smi"
    assert power.status is GpuTelemetryStatus.OBSERVED


def test_complete_nvml_unavailability_records_nvidia_smi_provenance():
    observation = probe_nvidia_host("worker-a", runner=_smi_runner, nvml_loader=lambda: None)

    telemetry = observation.gpus[0].telemetry
    assert telemetry.source == "nvidia-smi"
    assert telemetry.field("temperature_c").status is GpuTelemetryStatus.UNAVAILABLE
    assert telemetry.field("temperature_c").source == "nvidia-smi"


def test_unsupported_and_error_telemetry_are_explicit_not_fabricated():
    unsupported = TelemetryValue(
        status=GpuTelemetryStatus.UNSUPPORTED,
        value=None,
        source="nvml",
        observed_at=1_700_000_000,
        detail="MIG is not exposed by this device",
    )
    error = TelemetryValue(
        status=GpuTelemetryStatus.ERROR,
        value=None,
        source="nvml",
        observed_at=1_700_000_000,
        detail="NVML returned an error",
    )

    assert unsupported.value is None
    assert error.value is None
    assert unsupported.status is GpuTelemetryStatus.UNSUPPORTED
    assert error.status is GpuTelemetryStatus.ERROR


def test_telemetry_freshness_is_explicit():
    telemetry = GpuTelemetryEvidence(
        source="nvml",
        collected_at=1_700_000_000,
        collector="nvml",
        fields={
            "temperature_c": TelemetryValue(
                status=GpuTelemetryStatus.OBSERVED,
                value=61,
                source="nvml",
                observed_at=1_700_000_000,
            )
        },
    )

    assert telemetry.is_fresh(now=1_700_000_030, max_age_seconds=60)
    assert not telemetry.is_fresh(now=1_700_000_061, max_age_seconds=60)


def test_observation_serialization_and_digest_remain_deterministic_with_telemetry():
    telemetry = GpuTelemetryEvidence(
        source="nvml",
        collected_at=1_700_000_000,
        collector="nvml",
        fields={
            "temperature_c": TelemetryValue(
                status=GpuTelemetryStatus.OBSERVED,
                value=61,
                source="nvml",
                observed_at=1_700_000_000,
            )
        },
    )
    observation = GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=(
            GpuDeviceObservation(
                0,
                "GPU-aaa",
                "NVIDIA Test GPU",
                81920,
                0,
                "00000000:17:00.0",
                "10.0",
                telemetry=telemetry,
            ),
        ),
        topology_text=None,
        dcgm_available=False,
        dcgm_version=None,
        health_json=None,
    )

    payload = json.loads(observation.canonical_json())
    assert payload["gpus"][0]["telemetry"]["source"] == "nvml"
    assert observation.digest() == observation.digest()


def test_gpu_identity_and_inventory_uniqueness_remain_enforced():
    telemetry = GpuTelemetryEvidence(
        source="nvml",
        collected_at=1_700_000_000,
        collector="nvml",
        fields={},
    )
    gpu = GpuDeviceObservation(
        0,
        "GPU-aaa",
        "NVIDIA Test GPU",
        81920,
        0,
        "00000000:17:00.0",
        "10.0",
        telemetry=telemetry,
    )
    with pytest.raises(ValueError, match="GPU UUIDs must be unique"):
        GpuHostObservation(
            worker_id="worker-a",
            driver_version="580.95.05",
            cuda_supported_version="13.0",
            gpus=(gpu, gpu),
            topology_text=None,
            dcgm_available=False,
            dcgm_version=None,
            health_json=None,
        )


def test_existing_nvidia_smi_parsers_remain_intact():
    output = "0, GPU-aaa, NVIDIA Test GPU, 81920, 1024, 00000000:17:00.0, 10.0\n"
    assert parse_nvidia_smi_gpu_csv(output)[0].uuid == "GPU-aaa"
    assert parse_nvidia_smi_header(
        "NVIDIA-SMI 580.95.05 Driver Version: 580.95.05 CUDA Version: 13.0"
    ) == ("580.95.05", "13.0")
