from dataclasses import replace
import json

import pytest

from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.worker_control_plane import WorkerControlPlane
from studio.worker_control_server import WorkerControlServer
from studio.remote_worker import WorkerLifecycleAuthority
from studio.resources import ComputeResource
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


def observation(worker_id="worker-a", health='Overall Health: Healthy'):
    return GpuHostObservation(
        worker_id=worker_id,
        driver_version="580.00",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-0", "Test GPU", 8192, 0, "0000:01:00.0", "8.0"),),
        topology_text="GPU0 GPU1",
        dcgm_available=True,
        dcgm_version="4.0",
        health_json=health,
    )


def payload(worker_id="worker-a", health='Overall Health: Healthy'):
    observed = observation(worker_id, health)
    from studio.gpu_worker_agent import GpuWorkerAgent

    agent = GpuWorkerAgent(worker_id, observer=lambda: observed)
    return agent.registration_payload()


def server():
    observed = observation()
    resource = ComputeResource("worker-a", 8, 16 * 1024**3, gpu_count=1, vram_bytes=8 * 1024**3, logical_slots=2, scratch_bytes=20 * 1024**3, power_budget_watts=300)
    registry = WorkerRegistry((WorkerRecord("worker-a", resource, state=WorkerState.UNVERIFIED),))
    authority = WorkerLifecycleAuthority({"worker-a": "enrollment-secret"})
    return WorkerControlServer(WorkerControlPlane(registry, authority)), registry, authority


def test_registration_returns_access_token_and_binds_inventory():
    service, registry, _ = server()
    response = service.register({"authorization": "Bearer enrollment-secret", "payload": payload()}, now=10)

    assert response.status == 200
    body = json.loads(response.body)
    assert body["worker_id"] == "worker-a"
    assert body["access_token"]
    record = registry.get("worker-a")
    assert record.state == WorkerState.VERIFIED_AVAILABLE
    assert record.resource.gpu_count == 1


def test_registration_rejects_missing_or_wrong_enrollment_credential():
    service, _, _ = server()
    body = payload()

    with pytest.raises(PermissionError):
        service.register({"authorization": None, "payload": body}, now=10)
    with pytest.raises(PermissionError):
        service.register({"authorization": "Bearer wrong", "payload": body}, now=10)


def test_heartbeat_requires_bearer_access_and_updates_health():
    service, registry, _ = server()
    registration = service.register({"authorization": "Bearer enrollment-secret", "payload": payload()}, now=10)
    access_token = json.loads(registration.body)["access_token"]

    warning = payload(health="Overall Health: Warning")
    response = service.heartbeat({"authorization": f"Bearer {access_token}", "payload": warning}, now=20)

    assert response.status == 200
    assert registry.get("worker-a").state == WorkerState.VERIFIED_LIMITED


def test_heartbeat_rejects_stolen_token_for_different_worker():
    service, _, authority = server()
    registration = service.register({"authorization": "Bearer enrollment-secret", "payload": payload()}, now=10)
    access_token = json.loads(registration.body)["access_token"]

    forged = payload("worker-a")
    forged["worker_id"] = "worker-b"
    with pytest.raises(PermissionError):
        service.heartbeat({"authorization": f"Bearer {access_token}", "payload": forged}, now=20)
    assert authority.heartbeat_age("worker-a", 20) == 10


def test_http_body_parser_rejects_non_object_json():
    service, _, _ = server()
    with pytest.raises(ValueError, match="JSON object"):
        service.decode_json_body(json.dumps([1, 2, 3]).encode("utf-8"))
