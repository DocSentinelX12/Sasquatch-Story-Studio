from studio.compute_broker import ComputeBroker
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.gpu_topology import GpuTopologyEvidence
from studio.nccl_evidence import NCCLTestEvidence
from studio.remote_worker import WorkerLifecycleAuthority
from studio.resources import ComputeResource
from studio.worker_control_plane import WorkerControlPlane
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


def observation(health: str | None = "healthy") -> GpuHostObservation:
    health_json = None if health is None else f"Overall Health: {health}"
    return GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.0",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-0", "Test GPU", 16384, 512, "0000:01:00.0", "12.0"),),
        topology_text="GPU0\tX\tCPU Affinity",
        dcgm_available=health is not None,
        dcgm_version="4.0" if health is not None else None,
        health_json=health_json,
    )


def evidence_observation() -> GpuHostObservation:
    gpu = GpuDeviceObservation(0, "GPU-0", "Test GPU", 16384, 512, "0000:01:00.0", "12.0")
    topology = GpuTopologyEvidence(
        gpu_uuids=("GPU-0",),
        gpu_matrix=(("X",),),
        cpu_affinity=(("GPU-0", "0-15"),),
        nic_paths=(("GPU-0", "NIC0", "PIX"),),
        raw_text_sha256="c" * 64,
    )
    nccl = NCCLTestEvidence(
        executable="/opt/nccl-tests/all_reduce_perf",
        executable_sha256="a" * 64,
        command=("/opt/nccl-tests/all_reduce_perf", "-g", "1"),
        exit_code=0,
        output_sha256="b" * 64,
        gpu_uuids=("GPU-0",),
        topology_digest="c" * 64,
    )
    return GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.0",
        cuda_supported_version="13.0",
        gpus=(gpu,),
        topology_text="GPU0\tX\tNIC0\tCPU Affinity",
        dcgm_available=True,
        dcgm_version="4.0",
        health_json="Overall Health: healthy",
        nccl_evidence=nccl,
        topology_evidence=topology,
    )


def registry() -> WorkerRegistry:
    resource = ComputeResource("worker-a", 8, 16 * 1024**3, gpu_count=0, vram_bytes=0, logical_slots=2, scratch_bytes=20 * 1024**3, power_budget_watts=300)
    return WorkerRegistry((WorkerRecord("worker-a", resource, state=WorkerState.UNVERIFIED),))


def payload(obs: GpuHostObservation) -> dict:
    import hashlib
    import json

    identity = {
        "worker_id": obs.worker_id,
        "driver_version": obs.driver_version,
        "cuda_supported_version": obs.cuda_supported_version,
        "gpus": [
            {"uuid": g.uuid, "name": g.name, "pci_bus_id": g.pci_bus_id, "compute_capability": g.compute_capability, "memory_total_mib": g.memory_total_mib}
            for g in obs.gpus
        ],
        "topology_text": obs.topology_text,
    }
    return {
        "worker_id": obs.worker_id,
        "hardware_observation_digest": obs.digest(),
        "hardware_identity_digest": hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "hardware_observation": json.loads(obs.canonical_json()),
    }


def test_registration_binds_inventory_and_heartbeat_updates_health():
    registry_value = registry()
    authority = WorkerLifecycleAuthority({"worker-a": "enrollment-secret"})
    control = WorkerControlPlane(registry_value, authority)
    access = control.register(payload(observation()), "enrollment-secret", now=10)

    record = registry_value.get("worker-a")
    assert record.state == WorkerState.VERIFIED_AVAILABLE
    assert record.resource.gpu_count == 1
    assert record.resource.vram_bytes == 16384 * 1024 * 1024
    assert record.hardware_observation is not None

    limited = observation("warning")
    heartbeat = control.heartbeat(payload(limited), access, now=20)
    assert heartbeat.state == WorkerState.VERIFIED_LIMITED
    assert heartbeat.observed_at == 20


def test_control_plane_preserves_topology_and_nccl_evidence_across_auth_boundary():
    registry_value = registry()
    authority = WorkerLifecycleAuthority({"worker-a": "enrollment-secret"})
    control = WorkerControlPlane(registry_value, authority)
    access = control.register(payload(evidence_observation()), "enrollment-secret", now=10)

    stored = registry_value.get("worker-a").hardware_observation
    assert stored is not None
    assert stored.topology_evidence is not None
    assert stored.topology_evidence.gpu_uuids == ("GPU-0",)
    assert stored.topology_evidence.nic_paths == (("GPU-0", "NIC0", "PIX"),)
    assert stored.nccl_evidence is not None
    assert stored.nccl_evidence.gpu_uuids == ("GPU-0",)
    assert stored.nccl_evidence.topology_digest == "c" * 64
    assert stored.digest() == evidence_observation().digest()

    heartbeat = control.heartbeat(payload(evidence_observation()), access, now=20)
    assert heartbeat.hardware_observation is not None
    assert heartbeat.hardware_observation.digest() == evidence_observation().digest()


def test_health_failure_quarantines_worker():
    registry_value = registry()
    authority = WorkerLifecycleAuthority({"worker-a": "enrollment-secret"})
    control = WorkerControlPlane(registry_value, authority)
    access = control.register(payload(observation()), "enrollment-secret", now=10)

    failed = observation("failure")
    record = control.heartbeat(payload(failed), access, now=30)
    assert record.state == WorkerState.TEMPORARILY_UNAVAILABLE
    assert not record.resource.healthy


def test_heartbeat_rejects_inventory_identity_change():
    registry_value = registry()
    authority = WorkerLifecycleAuthority({"worker-a": "enrollment-secret"})
    control = WorkerControlPlane(registry_value, authority)
    access = control.register(payload(observation()), "enrollment-secret", now=10)

    changed = GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.0",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-OTHER", "Test GPU", 16384, 512, "0000:01:00.0", "12.0"),),
        topology_text="GPU0\tX\tCPU Affinity",
        dcgm_available=True,
        dcgm_version="4.0",
        health_json="Overall Health: healthy",
    )
    try:
        control.heartbeat(payload(changed), access, now=40)
    except PermissionError:
        pass
    else:
        raise AssertionError("changed physical GPU identity must be rejected")
