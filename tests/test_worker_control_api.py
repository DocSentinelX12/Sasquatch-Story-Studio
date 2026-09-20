import hashlib
import json

from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.remote_worker import WorkerLifecycleAuthority
from studio.scheduler import JobRequirements
from studio.worker import WorkerResult, WorkerResultState, WorkerTask
from studio.worker_control_api import WorkerControlApi
from studio.worker_control_plane import WorkerControlPlane
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState
from studio.resources import ComputeResource


def obs() -> GpuHostObservation:
    return GpuHostObservation(
        worker_id="worker-a", driver_version="580", cuda_supported_version="13",
        gpus=(GpuDeviceObservation(0, "GPU-0", "Test GPU", 16384, 512, "0000:01:00.0", "12.0"),),
        topology_text="GPU0 X", dcgm_available=True, dcgm_version="4", health_json="Overall Health: healthy",
    )


def identity(o: GpuHostObservation) -> str:
    return WorkerControlPlane._identity_digest(o)


def payload(o: GpuHostObservation) -> dict:
    return {"worker_id": o.worker_id, "hardware_observation_digest": o.digest(), "hardware_identity_digest": identity(o),
            "hardware_observation": json.loads(o.canonical_json())}


def setup():
    resource = ComputeResource("worker-a", 4, 16 * 1024**3, gpu_count=0, vram_bytes=0, logical_slots=2, scratch_bytes=1, power_budget_watts=300)
    registry = WorkerRegistry((WorkerRecord("worker-a", resource, state=WorkerState.UNVERIFIED),))
    authority = WorkerLifecycleAuthority({"worker-a": "enroll"})
    plane = WorkerControlPlane(registry, authority)
    return plane, authority


def test_register_heartbeat_and_execute_are_authenticated():
    plane, authority = setup()
    now = iter([10, 20, 20, 20])
    task = WorkerTask("task-1", "ep", "video", "shot", (), (), JobRequirements(engines=("wan",)), gpu_uuids=("GPU-0",))
    seen = []
    api = WorkerControlApi(plane, authority, clock=lambda: next(now), execute=lambda t, lease: (seen.append((t, lease)) or WorkerResult(t.task_id, WorkerResultState.COMPLETED, ("sha256:" + "a" * 64,))))

    registered = api.register(payload(obs()), {"Authorization": "Bearer enroll"})
    assert registered.status == 200
    token = registered.body["access_token"]
    assert api.heartbeat(payload(obs()), {"Authorization": f"Bearer {token}"}).status == 200

    access = __import__("studio.remote_worker", fromlist=["WorkerAccess"]).WorkerAccess("worker-a", token)
    lease = authority.issue_lease(access, task, expires_at=100, now=20)
    response = api.execute_lease({"worker_id": "worker-a", "lease": lease.__dict__, "task": {
        "task_id": task.task_id, "episode_id": task.episode_id, "stage": task.stage, "shot_id": task.shot_id,
        "input_refs": [], "input_hashes": [], "requirements": {"slots": 1, "memory_bytes": 0, "vram_bytes": 0, "scratch_bytes": 0, "power_watts": 0, "capabilities": [], "engines": ["wan"], "hardware": None},
        "provenance_context": [], "canonical_source_hash": "", "payload_json": "", "gpu_uuids": ["GPU-0"]}}, {"Authorization": f"Bearer {token}"})
    assert response.status == 200
    assert response.body["state"] == "completed"
    assert seen[0][0].gpu_uuids == ("GPU-0",)


def test_execute_rejects_replay():
    plane, authority = setup()
    now = iter([10, 20, 20, 20])
    task = WorkerTask("task-2", "ep", "video", "shot", (), (), JobRequirements(), gpu_uuids=("GPU-0",))
    api = WorkerControlApi(plane, authority, clock=lambda: next(now), execute=lambda t, lease: WorkerResult(t.task_id, WorkerResultState.COMPLETED))
    reg = api.register(payload(obs()), {"Authorization": "Bearer enroll"})
    token = reg.body["access_token"]
    access = __import__("studio.remote_worker", fromlist=["WorkerAccess"]).WorkerAccess("worker-a", token)
    lease = authority.issue_lease(access, task, 100, 20)
    body = {"worker_id": "worker-a", "lease": lease.__dict__, "task": {"task_id": task.task_id, "episode_id": "ep", "stage": "video", "shot_id": "shot", "input_refs": [], "input_hashes": [], "requirements": {"slots": 1, "memory_bytes": 0, "vram_bytes": 0, "scratch_bytes": 0, "power_watts": 0, "capabilities": [], "engines": [], "hardware": None}, "provenance_context": [], "canonical_source_hash": "", "payload_json": "", "gpu_uuids": ["GPU-0"]}}
    headers = {"Authorization": f"Bearer {token}"}
    assert api.execute_lease(body, headers).status == 200
    assert api.execute_lease(body, headers).status == 403
