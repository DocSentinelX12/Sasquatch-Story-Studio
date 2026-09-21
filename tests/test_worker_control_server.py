import json

import pytest

from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.remote_worker import WorkerLifecycleAuthority
from studio.worker import WorkerTask
from studio.worker_control_plane import WorkerControlPlane
from studio.worker_control_server import WorkerControlServer
from studio.resources import ComputeResource
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState
from studio.scheduler import JobRequirements


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


def server(execute=None):
    resource = ComputeResource("worker-a", 8, 16 * 1024**3, gpu_count=1, vram_bytes=8 * 1024**3, logical_slots=2, scratch_bytes=20 * 1024**3, power_budget_watts=300)
    registry = WorkerRegistry((WorkerRecord("worker-a", resource, state=WorkerState.UNVERIFIED),))
    authority = WorkerLifecycleAuthority({"worker-a": "enrollment-secret"})
    return WorkerControlServer(WorkerControlPlane(registry, authority), execute=execute), registry, authority


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


def test_execute_requires_valid_lease_and_rejects_replay():
    observed_results = []
    service, _, authority = server(
        execute=lambda payload, lease, access, now: observed_results.append((payload["task"]["task_id"], lease.lease_id, access.worker_id, now)) or {"state": "completed", "output_refs": ["sha256:" + "a" * 64]}
    )
    registration = service.register({"authorization": "Bearer enrollment-secret", "payload": payload()}, now=10)
    access_token = json.loads(registration.body)["access_token"]
    access = authority.register("worker-a", "enrollment-secret", now=11)
    # The second registration intentionally rotates access; use the current token.
    access_token = access.access_token
    task = WorkerTask("task-a", "ep-1", "video", "shot-1", (), (), JobRequirements(), gpu_uuids=("GPU-0",))
    lease = authority.issue_lease(access, task, expires_at=100, now=11)
    body = json.dumps({"lease": lease.__dict__, "task": {"task_id": task.task_id, "gpu_uuids": list(task.gpu_uuids)}}).encode("utf-8")

    response = service.dispatch("POST", "/v1/worker/execute", body, f"Bearer {access_token}", now=20)
    assert response.status == 200
    assert json.loads(response.body)["state"] == "completed"
    assert observed_results == [("task-a", lease.lease_id, "worker-a", 20)]

    replay = service.dispatch("POST", "/v1/worker/execute", body, f"Bearer {access_token}", now=21)
    assert replay.status == 401


def test_execute_rejects_expired_lease():
    service, _, authority = server(execute=lambda *_args: {"state": "completed"})
    access = authority.register("worker-a", "enrollment-secret", now=10)
    task = WorkerTask("task-expired", "ep-1", "video", "shot-1", (), (), JobRequirements())
    lease = authority.issue_lease(access, task, expires_at=20, now=10)
    body = json.dumps({"lease": lease.__dict__, "task": {"task_id": task.task_id}}).encode("utf-8")

    response = service.dispatch("POST", "/v1/worker/execute", body, f"Bearer {access.access_token}", now=20)
    assert response.status == 401


def test_http_body_parser_rejects_non_object_json():
    service, _, _ = server()
    with pytest.raises(ValueError, match="JSON object"):
        service.decode_json_body(json.dumps([1, 2, 3]).encode("utf-8"))



def test_authenticated_artifact_chunk_serves_exact_last_chunk(tmp_path):
    service, _, authority = server()
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"x" * (4 * 1024 * 1024 + 37))
    access = authority.register("worker-a", "enrollment-secret", now=10)
    digest = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    service._artifact_provider = lambda worker_id, requested_digest: source if worker_id == "worker-a" and requested_digest == digest else None

    data = service.get_artifact_chunk(
        f"/v1/worker/artifacts/worker-a/{digest}/chunks/1?offset={4 * 1024 * 1024}&size=37",
        f"Bearer {access.access_token}",
    )

    assert data == b"x" * 37


def test_artifact_chunk_rejects_other_worker_token(tmp_path):
    service, _, authority = server()
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"payload")
    access = authority.register("worker-a", "enrollment-secret", now=10)
    digest = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    service._artifact_provider = lambda worker_id, requested_digest: source

    with pytest.raises(PermissionError):
        service.get_artifact_chunk(
            f"/v1/worker/artifacts/worker-b/{digest}/chunks/0?offset=0&size=7",
            f"Bearer {access.access_token}",
        )


def test_artifact_chunk_rejects_oversized_requested_range(tmp_path):
    service, _, authority = server()
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    access = authority.register("worker-a", "enrollment-secret", now=10)
    digest = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    service._artifact_provider = lambda worker_id, requested_digest: source

    with pytest.raises(ValueError, match="artifact chunk range"):
        service.get_artifact_chunk(
            f"/v1/worker/artifacts/worker-a/{digest}/chunks/0?offset=0&size={4 * 1024 * 1024 + 1}",
            f"Bearer {access.access_token}",
        )


def test_http_handler_returns_binary_artifact_response(tmp_path):
    from studio.worker_control_server import WorkerControlHTTPHandler

    service, _, authority = server()
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"binary-payload")
    access = authority.register("worker-a", "enrollment-secret", now=10)
    digest = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    service._artifact_provider = lambda worker_id, requested_digest: source
    handler = WorkerControlHTTPHandler()
    handler.service = service
    handler.clock = lambda: 10

    response = handler.handle(
        "GET",
        f"/v1/worker/artifacts/worker-a/{digest}/chunks/0?offset=0&size=14",
        b"",
        f"Bearer {access.access_token}",
    )

    assert response.status == 200
    assert response.content_type == "application/octet-stream"
    assert response.body == b"binary-payload"
