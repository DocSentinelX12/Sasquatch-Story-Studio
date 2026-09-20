from dataclasses import dataclass

import pytest

from studio.compute_broker import ComputeBroker, ProductionTask
from studio.remote_worker import DistributedWorkerLease, RemoteWorkerExecutor, WorkerAccess, WorkerLifecycleAuthority
from studio.resources import ComputeResource
from studio.scheduler import JobRequirements, Scheduler
from studio.worker import WorkerResultState, WorkerTask
from studio.worker_fabric import DispatchState, WorkerFabric
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState
from studio.distributed_gpu import DistributedGpuAllocator
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation


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



def distributed_registry() -> WorkerRegistry:
    records = []
    for worker_id, offset in (("worker-a", 0), ("worker-b", 4)):
        gpus = tuple(
            GpuDeviceObservation(
                index=index,
                uuid=f"{worker_id}-GPU-{index}",
                name="NVIDIA Test GPU",
                memory_total_mib=80 * 1024,
                memory_used_mib=0,
                pci_bus_id=f"0000:{offset + index:02x}:00.0",
                compute_capability="9.0",
            )
            for index in range(4)
        )
        observation = GpuHostObservation(
            worker_id=worker_id,
            driver_version="test-driver",
            cuda_supported_version="12.9",
            gpus=gpus,
            topology_text="observed",
            dcgm_available=False,
            dcgm_version=None,
            health_json=None,
        )
        resource = ComputeResource(worker_id, 64, 256 * 1024**3, gpu_count=4, vram_bytes=320 * 1024**3, logical_slots=4, scratch_bytes=1024**12, power_budget_watts=2000)
        records.append(WorkerRecord(worker_id, resource, WorkerState.VERIFIED_AVAILABLE, observed_at=100, observation_source="test", hardware_observation=observation))
    return WorkerRegistry(tuple(records))

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


def test_lifecycle_authority_issues_exact_per_worker_distributed_lease():
    registry = distributed_registry()
    from studio.hardware_requirements import GpuPlacement, HardwareRequirements
    allocator = DistributedGpuAllocator(registry)
    requirements = HardwareRequirements(
        min_gpu_count=8,
        min_vram_per_gpu_bytes=80 * 1024**3,
        min_total_vram_bytes=8 * 80 * 1024**3,
        placement=GpuPlacement.MULTI_NODE,
        allow_multi_node=True,
    )
    allocation = allocator.reserve("task-distributed", requirements, now=100, lease_seconds=60)
    authority = WorkerLifecycleAuthority({"worker-a": "secret-a", "worker-b": "secret-b"})
    access = authority.register("worker-a", "secret-a", now=100, hardware_identity_digest=__import__("studio.worker_control_plane", fromlist=["WorkerControlPlane"]).WorkerControlPlane._identity_digest(registry.get("worker-a").hardware_observation))
    lease = authority.issue_distributed_lease(access, allocation, "task-distributed", now=101)

    assert isinstance(lease, DistributedWorkerLease)
    assert lease.worker_id == "worker-a"
    assert lease.world_size == 8
    assert lease.node_count == 2
    assert lease.node_rank == 0
    assert tuple(rank.local_rank for rank in lease.ranks) == (0, 1, 2, 3)
    authority.authorize_distributed_execution(access, lease, allocation, now=102)
    with pytest.raises(PermissionError, match="already been used"):
        authority.authorize_distributed_execution(access, lease, allocation, now=103)
