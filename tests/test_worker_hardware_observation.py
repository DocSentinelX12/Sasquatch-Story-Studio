from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.resources import ComputeResource
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


def observation():
    return GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=(
            GpuDeviceObservation(0, "GPU-aaa", "NVIDIA Test GPU", 81920, 0, "00000000:17:00.0", "10.0"),
            GpuDeviceObservation(1, "GPU-bbb", "NVIDIA Test GPU", 81920, 0, "00000000:18:00.0", "10.0"),
        ),
        topology_text="GPU0 GPU1 NVLink",
        dcgm_available=False,
        dcgm_version=None,
        health_json=None,
    )


def test_worker_record_can_carry_observed_gpu_hardware_without_inventing_it():
    record = WorkerRecord(
        id="worker-a",
        resource=ComputeResource(
            id="resource-a",
            cpu_cores=16,
            memory_bytes=64 * 1024**3,
            gpu_count=2,
            gpu_models=("NVIDIA Test GPU",),
            vram_bytes=160 * 1024**3,
            logical_slots=2,
        ),
        state=WorkerState.VERIFIED_AVAILABLE,
        hardware_observation=observation(),
    )
    assert record.hardware_observation is not None
    assert record.hardware_observation.gpu_count == 2
    assert record.hardware_observation.gpus[0].uuid == "GPU-aaa"


def test_registry_snapshot_preserves_hardware_observation():
    record = WorkerRecord(
        id="worker-a",
        resource=ComputeResource("resource-a", 16, 64 * 1024**3, gpu_count=2, vram_bytes=160 * 1024**3),
        state=WorkerState.VERIFIED_AVAILABLE,
        hardware_observation=observation(),
    )
    restored = WorkerRegistry((record,)).get("worker-a")
    assert restored.hardware_observation == record.hardware_observation
