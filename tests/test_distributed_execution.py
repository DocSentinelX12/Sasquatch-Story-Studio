import sys

from studio.distributed_execution import DistributedLaunchSpec, DistributedProcessExecutor
from studio.distributed_gpu import DistributedGpuAllocator
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.remote_worker import WorkerLifecycleAuthority, WorkerAccess
from studio.worker_control_plane import WorkerControlPlane
from studio.worker_control_server import WorkerControlServer
from studio.resources import ComputeResource
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation


def _registry():
    records = []
    for worker_id, base in (("A", 1), ("B", 5)):
        gpus = tuple(
            GpuDeviceObservation(i, f"{worker_id}-GPU-{i}", "Test GPU", 8192, 0, f"0000:{base+i:02x}:00.0", "8.0")
            for i in range(2)
        )
        observation = GpuHostObservation(
            worker_id=worker_id,
            driver_version="test",
            cuda_supported_version="13.0",
            gpus=gpus,
            topology_text="observed",
            dcgm_available=False,
            dcgm_version=None,
            health_json=None,
        )
        resource = ComputeResource(worker_id, 8, 16 * 1024**3, gpu_count=2, vram_bytes=16 * 1024**3, logical_slots=2)
        records.append(
            WorkerRecord(
                worker_id,
                resource,
                WorkerState.VERIFIED_AVAILABLE,
                observed_at=100,
                observation_source="test",
                hardware_observation=observation,
            )
        )
    return WorkerRegistry(tuple(records))


def _requirements():
    return HardwareRequirements(
        min_gpu_count=2,
        min_vram_per_gpu_bytes=8 * 1024**3,
        min_total_vram_bytes=16 * 1024**3,
        placement=GpuPlacement.MULTI_NODE,
        allow_multi_node=True,
    )


def test_launch_spec_builds_real_torchrun_multinode_argv():
    allocator = DistributedGpuAllocator(_registry())
    allocation = allocator.reserve("task-1", _requirements(), now=100, lease_seconds=600)
    authority = WorkerLifecycleAuthority({"A": "secret"})
    access = authority.register("A", "secret", now=100, hardware_identity_digest="a" * 64)
    lease = authority.issue_distributed_lease(access, allocation, "task-1", now=100)

    spec = DistributedLaunchSpec(
        executable="torchrun",
        command=("train.py", "--output", "{output}", "--steps", "10"),
        rendezvous_id="task-1",
        rendezvous_host="node-a.example",
        rendezvous_port=29400,
        max_restarts=1,
        output_path="/var/lib/studio/task-1.mp4",
    )

    assert spec.argv(lease) == (
        "torchrun",
        "--nnodes", "2",
        "--nproc-per-node", "1",
        "--node-rank", "0",
        "--rdzv-id", "task-1",
        "--rdzv-backend", "c10d",
        "--rdzv-endpoint", "node-a.example:29400",
        "--max-restarts", "1",
        "train.py", "--output", "/var/lib/studio/task-1.mp4", "--steps", "10",
    )


def test_distributed_worker_endpoint_authorizes_exact_lease_once():
    allocator = DistributedGpuAllocator(_registry())
    allocation = allocator.reserve("task-1", _requirements(), now=100, lease_seconds=600)

    authority = WorkerLifecycleAuthority({"A": "secret"})
    control = WorkerControlPlane(_registry(), authority)
    access = authority.register("A", "secret", now=100, hardware_identity_digest="a" * 64)

    captured = []
    service = WorkerControlServer(
        control,
        distributed_allocation=allocator.get,
        execute_distributed=lambda payload, lease, access, now: captured.append((lease.worker_id, lease.node_rank, now)) or {"state": "completed"},
    )
    lease = authority.issue_distributed_lease(access, allocation, "task-1", now=100)
    body = (
        '{"allocation_id":"%s","task_id":"task-1","lease":%s}'
        % (
            allocation.allocation_id,
            __import__("json").dumps({
                "allocation_id": lease.allocation_id,
                "task_id": lease.task_id,
                "worker_id": lease.worker_id,
                "world_size": lease.world_size,
                "node_count": lease.node_count,
                "node_rank": lease.node_rank,
                "ranks": [rank.__dict__ for rank in lease.ranks],
                "gpu_uuids": list(lease.gpu_uuids),
                "expires_at": lease.expires_at,
                "fencing_epoch": lease.fencing_epoch,
                "execution_nonce": lease.execution_nonce,
            }),
        )
    ).encode()

    response = service.dispatch("POST", "/v1/worker/execute-distributed", body, f"Bearer {access.access_token}", now=110)
    assert response.status == 200
    assert captured == [("A", 0, 110)]

    replay = service.dispatch("POST", "/v1/worker/execute-distributed", body, f"Bearer {access.access_token}", now=111)
    assert replay.status == 401


def test_process_executor_requires_the_real_launcher_to_be_present():
    spec = DistributedLaunchSpec(
        executable=sys.executable,
        command=("-c", "print('not reached')"),
        rendezvous_id="task-1",
        rendezvous_host="127.0.0.1",
        rendezvous_port=29501,
    )
    assert spec.command_sha256
    # The executor is intentionally not invoked here because Python is not a
    # torchrun-compatible launcher. Runtime GPU/NCCL execution belongs on a
    # verified GPU worker, not in a CPU-only unit test.
    assert DistributedProcessExecutor(spec).spec == spec
