from dataclasses import dataclass

import pytest

from studio.compute_broker import ComputeBroker, ProductionTask
from studio.remote_worker import RemoteWorkerExecutor, WorkerAccess, WorkerLifecycleAuthority
from studio.resources import ComputeResource
from studio.scheduler import JobRequirements, Scheduler
from studio.worker import WorkerResultState, WorkerTask
from studio.worker_fabric import DispatchState, WorkerFabric
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


@dataclass
class FakeTransport:
    response: dict
    path: str | None = None
    payload: dict | None = None
    token: str | None = None

    def post_json(self, path, payload, *, bearer_token):
        self.path = path
        self.payload = payload
        self.token = bearer_token
        return self.response


def task(worker_id: str = "worker-a") -> WorkerTask:
    return WorkerTask(
        "task-remote",
        "episode-1",
        "animate",
        "shot-1",
        (),
        (),
        JobRequirements(),
        (("worker_id", worker_id),),
        "a" * 64,
        '{"engine_id":"hunyuanvideo-1.5","parameters":{"prompt":"test"}}',
        ("GPU-0",),
    )


def test_lifecycle_authority_enrolls_heartbeats_and_rejects_replay():
    authority = WorkerLifecycleAuthority({"worker-a": "enrollment-secret"})
    access = authority.register("worker-a", "enrollment-secret", now=10)
    authority.heartbeat(access, now=20)
    lease = authority.issue_lease(access, task(), expires_at=100, now=20)

    authority.authorize_execution(access, lease, now=21)
    with pytest.raises(PermissionError, match="already been used"):
        authority.authorize_execution(access, lease, now=22)

    authority.complete_lease(access, lease, now=23)
    assert authority.heartbeat_age("worker-a", 25) == 5


def test_remote_executor_sends_exact_lease_and_gpu_allocation():
    authority = WorkerLifecycleAuthority({"worker-a": "enrollment-secret"})
    access = authority.register("worker-a", "enrollment-secret", now=10)
    transport = FakeTransport({"state": "completed", "output_refs": ["sha256:output"]})
    executor = RemoteWorkerExecutor(transport, access)
    remote_task = task()
    lease = authority.issue_lease(access, remote_task, expires_at=100, now=10)

    result = executor.execute_with_lease(remote_task, lease)

    assert result.state == WorkerResultState.COMPLETED
    assert transport.path == "/v1/worker/execute"
    assert transport.payload["lease"]["gpu_uuids"] == ["GPU-0"] or tuple(transport.payload["lease"]["gpu_uuids"]) == ("GPU-0",)
    assert transport.payload["task"]["gpu_uuids"] == ("GPU-0",)
    assert transport.token == access.access_token


def test_worker_fabric_requires_authorized_lease_provider_for_remote_executor():
    scheduler = Scheduler()
    resource = ComputeResource("worker-a", 8, 16 * 1024**3, gpu_count=1, vram_bytes=8 * 1024**3, logical_slots=2, scratch_bytes=20 * 1024**3, power_budget_watts=300)
    registry = WorkerRegistry((WorkerRecord("worker-a", resource, state=WorkerState.VERIFIED_AVAILABLE),))
    broker = ComputeBroker(scheduler, registry)
    production_task = ProductionTask("task-remote", JobRequirements())
    broker.submit(production_task)
    authority = WorkerLifecycleAuthority({"worker-a": "enrollment-secret"})
    access = authority.register("worker-a", "enrollment-secret", now=10)
    executor = RemoteWorkerExecutor(FakeTransport({"state": "completed", "output_refs": ["sha256:output"]}), access)
    fabric = WorkerFabric(broker, {"worker-a": executor})

    result = fabric.dispatch(production_task, lambda task_value, job, worker_id: task(worker_id), now=10)

    assert result.state == DispatchState.REQUEUED
    assert "lease provider" in (result.error or "")


def test_worker_fabric_uses_control_plane_lease_provider_for_remote_executor():
    scheduler = Scheduler()
    resource = ComputeResource("worker-a", 8, 16 * 1024**3, gpu_count=1, vram_bytes=8 * 1024**3, logical_slots=2, scratch_bytes=20 * 1024**3, power_budget_watts=300)
    registry = WorkerRegistry((WorkerRecord("worker-a", resource, state=WorkerState.VERIFIED_AVAILABLE),))
    broker = ComputeBroker(scheduler, registry)
    production_task = ProductionTask("task-remote", JobRequirements())
    broker.submit(production_task)
    authority = WorkerLifecycleAuthority({"worker-a": "enrollment-secret"})
    access = authority.register("worker-a", "enrollment-secret", now=10)
    transport = FakeTransport({"state": "completed", "output_refs": ["sha256:output"]})
    executor = RemoteWorkerExecutor(transport, access)

    def lease_provider(worker_id, worker_task, expires_at, now):
        assert worker_id == "worker-a"
        return authority.issue_lease(access, worker_task, expires_at=expires_at, now=now)

    fabric = WorkerFabric(broker, {"worker-a": executor}, lease_provider=lease_provider)
    result = fabric.dispatch(production_task, lambda task_value, job, worker_id: task(worker_id), now=10)

    assert result.state == DispatchState.COMPLETED
    assert result.output_refs == ("sha256:output",)
    assert transport.path == "/v1/worker/execute"
