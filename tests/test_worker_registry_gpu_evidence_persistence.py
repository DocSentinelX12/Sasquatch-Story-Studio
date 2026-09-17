import hashlib

from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.gpu_topology import GpuTopologyEvidence
from studio.resources import ComputeResource
from studio.worker_registry import SQLiteWorkerRegistryStore, WorkerRecord, WorkerRegistry, WorkerState


def test_gpu_topology_evidence_survives_sqlite_round_trip(tmp_path):
    raw = """        GPU0 GPU1 CPU Affinity NUMA Affinity
GPU0      X  NV4  0-31        0
GPU1    NV4    X  0-31        0
"""
    gpus = (
        GpuDeviceObservation(0, "GPU-A", "observed-gpu", 24576, 1024, "0000:01:00.0", "8.0"),
        GpuDeviceObservation(1, "GPU-B", "observed-gpu", 24576, 2048, "0000:02:00.0", "8.0"),
    )
    topology = GpuTopologyEvidence(
        gpu_uuids=("GPU-A", "GPU-B"),
        gpu_matrix=(("X", "NV4"), ("NV4", "X")),
        cpu_affinity=(("GPU-A", "0-31"), ("GPU-B", "0-31")),
        nic_paths=(),
        raw_text_sha256=hashlib.sha256(raw.encode()).hexdigest(),
    )
    observation = GpuHostObservation(
        "worker-a", "550.0", "12.4", gpus, raw, False, None, None,
        topology_evidence=topology,
    )
    resource = ComputeResource("resource-a", 16, 32 * 1024**3, gpu_count=2, gpu_models=("observed-gpu",), vram_bytes=48 * 1024**3)
    registry = WorkerRegistry((WorkerRecord("worker-a", resource, WorkerState.VERIFIED_AVAILABLE, hardware_observation=observation),))
    store = SQLiteWorkerRegistryStore(tmp_path / "workers.sqlite")
    store.save(registry)
    restored = store.load().get("worker-a").hardware_observation
    assert restored is not None
    assert restored.topology_evidence is not None
    assert restored.topology_evidence.gpu_uuids == ("GPU-A", "GPU-B")
    assert restored.topology_evidence.relationship("GPU-A", "GPU-B") == "NV4"
