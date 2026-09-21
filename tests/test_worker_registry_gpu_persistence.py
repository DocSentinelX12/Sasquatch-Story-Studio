from studio.gpu_capabilities import derive_gpu_capabilities
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.resources import ComputeResource
from studio.worker_registry import SQLiteWorkerRegistryStore, WorkerRecord, WorkerRegistry, WorkerState


def test_sqlite_registry_round_trips_observed_gpu_identity(tmp_path):
    observation = GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-aaa", "NVIDIA Test GPU", 81920, 0, "00000000:17:00.0", "10.0"),),
        topology_text="GPU0",
        dcgm_available=False,
        dcgm_version=None,
        health_json=None,
    )
    record = WorkerRecord(
        id="worker-a",
        resource=ComputeResource("resource-a", 16, 64 * 1024**3, gpu_count=1, vram_bytes=80 * 1024**3),
        state=WorkerState.VERIFIED_AVAILABLE,
        hardware_observation=observation,
    )
    registry = WorkerRegistry((record,))
    store = SQLiteWorkerRegistryStore(tmp_path / "workers.sqlite")
    store.save(registry)
    restored = store.load().get("worker-a")
    assert restored.hardware_observation == observation


def test_sqlite_registry_round_trips_canonical_gpu_capabilities(tmp_path):
    observation = GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-aaa", "NVIDIA Test GPU", 81920, 0, "00000000:17:00.0", "10.0"),),
        topology_text="GPU0",
        dcgm_available=False,
        dcgm_version=None,
        health_json=None,
        observed_at=100,
        collector_identity="test",
    )
    capabilities = derive_gpu_capabilities(observation, now=100)
    record = WorkerRecord(
        id="worker-a",
        resource=ComputeResource("resource-a", 16, 64 * 1024**3, gpu_count=1, vram_bytes=80 * 1024**3),
        state=WorkerState.VERIFIED_LIMITED,
        hardware_observation=observation,
        gpu_capabilities=capabilities,
    )
    registry = WorkerRegistry((record,))
    store = SQLiteWorkerRegistryStore(tmp_path / "workers.sqlite")
    store.save(registry)
    restored = store.load().get("worker-a")
    assert restored.gpu_capabilities == capabilities
    assert restored.gpu_capabilities.records[0].gpu_uuid == "GPU-aaa"
