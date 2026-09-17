from studio.compute_broker import ComputeBroker, ProductionTask
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.scheduler import JobRequirements, Scheduler
from studio.worker_registry import WorkerRegistry


def record(worker_id="gpu", vram=96 * 1024**3, hardware=None):
    from studio.resources import ComputeResource

    return __import__("studio.worker_registry", fromlist=["WorkerRecord"]).WorkerRecord(
        id=worker_id,
        state=__import__("studio.worker_registry", fromlist=["WorkerState"]).WorkerState.VERIFIED_AVAILABLE,
        resource=ComputeResource(
            logical_slots=8,
            memory_bytes=128 * 1024**3,
            vram_bytes=vram,
            scratch_bytes=1024**3,
            power_budget_watts=1000,
            capabilities=frozenset({"video_generation"}),
            installed_engines=frozenset(),
            healthy=True,
        ),
        hardware_observation=hardware,
    )


def test_topology_sensitive_hardware_is_rejected_without_verified_placement_evidence():
    hardware = GpuHostObservation(
        worker_id="gpu",
        driver_version="580.00",
        cuda_supported_version="13.0",
        gpus=(
            GpuDeviceObservation(0, "GPU-0", "Observed GPU", 96 * 1024, 0, "0000:01:00.0", "10.0"),
            GpuDeviceObservation(1, "GPU-1", "Observed GPU", 96 * 1024, 0, "0000:02:00.0", "10.0"),
        ),
        topology_text="GPU0 GPU1\nGPU1 GPU0",
        dcgm_available=False,
        dcgm_version=None,
        health_json=None,
    )
    registry = WorkerRegistry((record("gpu", vram=192 * 1024**3, hardware=hardware),))
    broker = ComputeBroker(Scheduler(), registry)
    task = ProductionTask(
        "t",
        JobRequirements(hardware=HardwareRequirements(min_gpu_count=2, placement=GpuPlacement.SAME_NVLINK_DOMAIN)),
    )
    decision = broker.select_worker(task)
    assert decision.selected_worker is None
    assert dict(decision.rejected_workers)["gpu"] == "verified NVIDIA topology evidence is missing"


def test_lease_binds_the_requested_task_and_exact_gpu_allocation():
    hardware = GpuHostObservation(
        worker_id="gpu",
        driver_version="580.00",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-0", "Observed GPU", 96 * 1024, 0, "0000:01:00.0", "10.0"),),
        topology_text="GPU0 GPU0",
        dcgm_available=False,
        dcgm_version=None,
        health_json=None,
    )
    scheduler = Scheduler()
    registry = WorkerRegistry((record("gpu", vram=96 * 1024**3, hardware=hardware),))
    broker = ComputeBroker(scheduler, registry)
    requested = ProductionTask("requested", JobRequirements(hardware=HardwareRequirements(min_gpu_count=1)))
    decision, job = broker.lease(requested, now=0)
    assert decision.selected_worker == "gpu"
    assert decision.selected_gpu_uuids == ("GPU-0",)
    assert job is not None
    assert job.id == "requested"
