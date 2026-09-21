import types

import studio.gpu_infrastructure as gpu_infrastructure


def test_probe_prefers_nvml_before_nvidia_smi(monkeypatch):
    calls = []

    class FakeUtilization:
        gpu = 17
        memory = 23

    class FakeMemory:
        total = 80 * 1024**3
        used = 4 * 1024**3
        free = total - used

    class FakeNvml:
        NVML_TEMPERATURE_GPU = 0
        NVML_TEMPERATURE_THRESHOLD_SHUTDOWN = 0
        NVML_TEMPERATURE_THRESHOLD_SLOWDOWN = 1
        NVML_TEMPERATURE_THRESHOLD_MEM = 2
        NVML_TEMPERATURE_THRESHOLD_BOARD = 3
        NVML_FAN_SPEED = 0
        NVML_CLOCK_GRAPHICS = 0
        NVML_CLOCK_MEM = 1
        NVML_PCI_DEV = 0

        def nvmlInit(self):
            calls.append("nvmlInit")

        def nvmlShutdown(self):
            calls.append("nvmlShutdown")

        def nvmlSystemGetDriverVersion(self):
            return "580.95.05"

        def nvmlSystemGetCudaDriverVersion_v2(self):
            return 13000

        def nvmlDeviceGetCount(self):
            calls.append("nvmlDeviceGetCount")
            return 1

        def nvmlDeviceGetHandleByIndex(self, index):
            calls.append(("handle", index))
            return "handle-0"

        def nvmlDeviceGetUUID(self, handle):
            calls.append("uuid")
            return "GPU-aaa"

        def nvmlDeviceGetName(self, handle):
            return "NVIDIA Test GPU"

        def nvmlDeviceGetMemoryInfo(self, handle):
            return FakeMemory()

        def nvmlDeviceGetPciInfo(self, handle):
            return types.SimpleNamespace(busId=b"00000000:17:00.0")

        def nvmlDeviceGetCudaComputeCapability(self, handle):
            return (10, 0)

        def nvmlDeviceGetTemperature(self, handle, sensor):
            return 55

        def nvmlDeviceGetPowerUsage(self, handle):
            return 250000

        def nvmlDeviceGetEnforcedPowerLimit(self, handle):
            return 700000

        def nvmlDeviceGetUtilizationRates(self, handle):
            return FakeUtilization()

        def nvmlDeviceGetEccMode(self, handle):
            return (0, 0)

        def nvmlDeviceGetTotalEccErrors(self, handle, *args):
            return 0

        def nvmlDeviceGetMigMode(self, handle):
            return (0, 0)

        def nvmlDeviceGetPcieLinkGeneration(self, handle):
            return 4

        def nvmlDeviceGetPcieLinkWidth(self, handle):
            return 16

        def nvmlDeviceGetPcieThroughput(self, handle, counter):
            return 100

        def nvmlDeviceGetNvLinkState(self, handle, link):
            return 1

    fake_nvml = FakeNvml()

    def fake_loader():
        return fake_nvml

    monkeypatch.setattr(gpu_infrastructure, "_load_nvml", fake_loader)
    monkeypatch.setattr(
        gpu_infrastructure.shutil,
        "which",
        lambda command: "/usr/bin/nvidia-smi" if command == "nvidia-smi" else None,
    )

    def fail_runner(command):
        calls.append(("smi", tuple(command)))
        raise AssertionError("nvidia-smi must not be used when NVML supplies the required observations")

    observation = gpu_infrastructure.probe_nvidia_host("worker-a", runner=fail_runner, now=100)
    assert observation.gpus[0].uuid == "GPU-aaa"
    assert observation.gpus[0].telemetry.temperature_c.value == 55
    assert observation.gpus[0].telemetry.temperature_c.source == "nvml"
    assert "nvmlInit" in calls

def test_probe_records_explicit_nvidia_smi_fallback_provenance(monkeypatch):
    monkeypatch.setattr(gpu_infrastructure.shutil, "which", lambda command: "/usr/bin/nvidia-smi" if command == "nvidia-smi" else None)

    outputs = {
        ("nvidia-smi",): "NVIDIA-SMI 580.95.05 Driver Version: 580.95.05 CUDA Version: 13.0",
        ("nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.used,pci.bus_id,compute_cap", "--format=csv,noheader,nounits"):
            "0, GPU-aaa, NVIDIA Test GPU, 81920, 1024, 00000000:17:00.0, 10.0",
        ("nvidia-smi", "--query-gpu=index,temperature.gpu,power.draw,power.limit,utilization.gpu,utilization.memory,ecc.errors.uncorrected.aggregate,mig.mode.current,pcie.link.gen.current,pcie.link.width.current,pcie.tx_util,pcie.rx_util", "--format=csv,noheader,nounits"):
            "0, 55, 250, 700, 17, 23, 0, Disabled, 4, 16, 100, 120",
        ("nvidia-smi", "topo", "-m"): "GPU0 CPU Affinity NUMA Affinity\nGPU0 X 0-3 0",
    }

    def runner(command):
        class Result:
            returncode = 0
            stderr = ""
        Result.stdout = outputs[tuple(command)]
        return Result()

    observation = gpu_infrastructure.probe_nvidia_host(
        "worker-a",
        runner=runner,
        now=100,
        nvml_loader=lambda: None,
    )
    telemetry = observation.gpus[0].telemetry
    assert observation.collector_identity == "nvidia-smi"
    assert telemetry.collector_identity == "nvidia-smi"
    assert telemetry.temperature_c.value == 55.0
    assert telemetry.temperature_c.source == "nvidia-smi"


def test_telemetry_freshness_rejects_stale_evidence():
    telemetry = gpu_infrastructure.GpuTelemetryObservation(
        **{
            name: gpu_infrastructure.TelemetryEvidence(
                gpu_infrastructure.TelemetryStatus.OBSERVED,
                1,
                "test",
                100,
            )
            for name in (
                "temperature_c", "power_usage_w", "power_limit_w", "utilization_percent",
                "memory_utilization_percent", "ecc_errors", "mig_mode", "nvlink_state",
                "pcie_link_generation", "pcie_link_width", "pcie_tx_kb_s", "pcie_rx_kb_s",
            )
        },
        xid_errors=gpu_infrastructure.TelemetryEvidence(gpu_infrastructure.TelemetryStatus.UNSUPPORTED, None, "test", 100),
        dcgm_health=gpu_infrastructure.TelemetryEvidence(gpu_infrastructure.TelemetryStatus.UNAVAILABLE, None, "test", 100),
        collector_identity="test",
    )
    assert not telemetry.is_fresh(200, 50, ["temperature_c"])
    assert telemetry.is_fresh(120, 50, ["temperature_c"])

def test_probe_falls_back_as_a_whole_when_nvml_cannot_supply_required_identity():
    calls = []

    class IncompleteNvml:
        def nvmlInit(self):
            calls.append("nvmlInit")

        def nvmlDeviceGetCount(self):
            return 1

        def nvmlDeviceGetHandleByIndex(self, index):
            return "handle"

        def nvmlDeviceGetUUID(self, handle):
            return "GPU-aaa"

        def nvmlDeviceGetName(self, handle):
            return "NVIDIA Test GPU"

        def nvmlDeviceGetMemoryInfo(self, handle):
            return types.SimpleNamespace(total=81920 * 1024**2, used=0)

        def nvmlDeviceGetPciInfo(self, handle):
            return types.SimpleNamespace(busId=b"00000000:17:00.0")

        def nvmlDeviceGetCudaComputeCapability(self, handle):
            return (10, 0)

        def nvmlShutdown(self):
            calls.append("nvmlShutdown")

    outputs = {
        ("nvidia-smi",): "NVIDIA-SMI 580.95.05 Driver Version: 580.95.05 CUDA Version: 13.0",
        ("nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.used,pci.bus_id,compute_cap", "--format=csv,noheader,nounits"):
            "0, GPU-bbb, NVIDIA Test GPU, 81920, 1024, 00000000:17:00.0, 10.0",
        ("nvidia-smi", "--query-gpu=index,temperature.gpu,power.draw,power.limit,utilization.gpu,utilization.memory,ecc.errors.uncorrected.aggregate,mig.mode.current,pcie.link.gen.current,pcie.link.width.current,pcie.tx_util,pcie.rx_util", "--format=csv,noheader,nounits"):
            "0, 55, 250, 700, 17, 23, 0, Disabled, 4, 16, 100, 120",
        ("nvidia-smi", "topo", "-m"): "GPU0 CPU Affinity NUMA Affinity\nGPU0 X 0-3 0",
    }

    monkeypatch = __import__("pytest").MonkeyPatch()
    try:
        monkeypatch.setattr(gpu_infrastructure.shutil, "which", lambda command: "/usr/bin/nvidia-smi" if command == "nvidia-smi" else None)
        def runner(command):
            class Result:
                returncode = 0
                stderr = ""
            Result.stdout = outputs[tuple(command)]
            return Result()
        observation = gpu_infrastructure.probe_nvidia_host(
            "worker-a", runner=runner, now=100, nvml_loader=lambda: IncompleteNvml()
        )
    finally:
        monkeypatch.undo()
    assert observation.collector_identity == "nvidia-smi"
    assert observation.gpus[0].uuid == "GPU-bbb"
    assert "nvmlInit" in calls
