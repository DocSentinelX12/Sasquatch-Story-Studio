import pytest

from studio.resources import ComputeResource
from studio.workers import Worker, WorkerHeartbeat, WorkerRegistry


def worker():
    resource = ComputeResource("gpu-1", 16, 32 * 1024**3, gpu_count=1, vram_bytes=24 * 1024**3, logical_slots=40)
    heartbeat = WorkerHeartbeat("worker-1", observed_at=10, utilization_percent=20)
    return Worker("worker-1", resource, heartbeat)


def test_worker_registry_registers_and_updates_heartbeat():
    registry = WorkerRegistry()
    registry.register(worker())
    registry.heartbeat(WorkerHeartbeat("worker-1", observed_at=20, utilization_percent=80))
    assert registry.snapshot()[0].heartbeat.observed_at == 20
    assert registry.snapshot()[0].heartbeat.utilization_percent == 80


def test_unknown_worker_heartbeat_is_rejected():
    with pytest.raises(KeyError):
        WorkerRegistry().heartbeat(WorkerHeartbeat("missing", observed_at=1))


def test_unhealthy_heartbeat_removes_resource_from_healthy_view():
    registry = WorkerRegistry([worker()])
    registry.heartbeat(WorkerHeartbeat("worker-1", observed_at=30, healthy=False))
    assert registry.healthy_resources() == ()
