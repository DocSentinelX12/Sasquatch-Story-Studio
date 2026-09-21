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
