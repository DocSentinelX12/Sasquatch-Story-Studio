from studio.gpu_aware_scheduler import GpuAwareScheduler
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation, GpuTelemetryEvidence, GpuTelemetryStatus, TelemetryValue
from studio.hardware_requirements import HardwareRequirements
from studio.resources import ComputeResource
from studio.scheduler import Job, JobRequirements, Scheduler
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


def test_gpu_aware_scheduler_reserves_specific_gpu_uuids_for_a_lease():
    telemetry = GpuTelemetryEvidence("fixture", 100, "test", {"temperature_c": TelemetryValue(GpuTelemetryStatus.OBSERVED, 60, "fixture", 100)})
    observation = GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=tuple(GpuDeviceObservation(i, f"GPU-{i}", "NVIDIA Test GPU", 81920, 0, f"00000000:{17+i:02x}:00.0", "10.0", telemetry=telemetry) for i in range(2)),
        topology_text="GPU0 GPU1\nGPU0 X NV2\nGPU1 NV2 X",
        dcgm_available=True,
        dcgm_version="test",
        health_json="Overall Health: Healthy",
    )
    record = WorkerRecord("worker-a", ComputeResource("resource-a", 16, 64 * 1024**3, gpu_count=2, vram_bytes=160 * 1024**3, logical_slots=2), WorkerState.VERIFIED_AVAILABLE, hardware_observation=observation)
    registry = WorkerRegistry((record,))
    scheduler = Scheduler((Job("job-a", JobRequirements(slots=2, hardware=HardwareRequirements(min_gpu_count=2))),))
    aware = GpuAwareScheduler(scheduler, registry)
    lease = aware.choose_on_worker("worker-a", now=100)
    assert lease is not None
    assert aware.allocated_gpus("job-a") == ("GPU-0", "GPU-1")


def test_gpu_aware_scheduler_releases_gpu_uuids_on_completion():
    telemetry = GpuTelemetryEvidence("fixture", 100, "test", {"temperature_c": TelemetryValue(GpuTelemetryStatus.OBSERVED, 60, "fixture", 100)})
    observation = GpuHostObservation("worker-a", "580.95.05", "13.0", (GpuDeviceObservation(0, "GPU-0", "NVIDIA Test GPU", 81920, 0, "00000000:17:00.0", "10.0", telemetry=telemetry),), "GPU0", True, "test", "Overall Health: Healthy")
    record = WorkerRecord("worker-a", ComputeResource("resource-a", 16, 64 * 1024**3, gpu_count=1, vram_bytes=80 * 1024**3), WorkerState.VERIFIED_AVAILABLE, hardware_observation=observation)
    registry = WorkerRegistry((record,))
    scheduler = Scheduler((Job("job-a", JobRequirements(slots=1, hardware=HardwareRequirements(min_gpu_count=1))),))
    aware = GpuAwareScheduler(scheduler, registry)
    aware.choose_on_worker("worker-a", now=100)
    aware.complete("job-a", "worker-a")
    assert aware.allocated_gpus("job-a") == ()
