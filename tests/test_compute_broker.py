import pytest

from studio.compute_broker import ComputeBroker, ProductionTask
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation, GpuTelemetryEvidence, GpuTelemetryStatus, TelemetryValue
from studio.gpu_topology import GpuTopologyEvidence
from studio.hardware_requirements import GpuPlacement, HardwareRequirements
from studio.resources import ComputeResource
from studio.scheduler import Job, JobRequirements, JobState, Scheduler
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


def record(worker_id, *, vram, capabilities=(), engines=(), state=WorkerState.VERIFIED_AVAILABLE, hardware=None):
    return WorkerRecord(
        worker_id,
        ComputeResource(
            worker_id + "-resource", 16, 32 * 1024**3, gpu_count=1,
            vram_bytes=vram, capabilities=capabilities, installed_engines=engines,
            logical_slots=4, scratch_bytes=100 * 1024**3, power_budget_watts=500,
        ), state=state, hardware_observation=hardware,
    )


def test_routes_only_to_observed_capabilities_and_runtime_verified_engine():
    registry = WorkerRegistry((
        record("small", vram=8 * 1024**3, capabilities=("video",), engines=("wan",)),
        record("strong", vram=24 * 1024**3, capabilities=("video", "cuda"), engines=("wan",)),
    ))
    broker = ComputeBroker(Scheduler(), registry, verified_engines=("wan",))
    task = ProductionTask("shot-1", JobRequirements(vram_bytes=16 * 1024**3, capabilities=("cuda",), engines=("wan",)))
    decision = broker.select_worker(task)
    assert decision.selected_worker == "strong"
    assert dict(decision.rejected_workers)["small"] == "insufficient VRAM"


def test_unavailable_worker_is_never_selected():
    registry = WorkerRegistry((record("offline", vram=32 * 1024**3, state=WorkerState.OFFLINE),))
    decision = ComputeBroker(Scheduler(), registry).select_worker(ProductionTask("t", JobRequirements()))
    assert decision.selected_worker is None
    assert decision.rejected_workers == (("offline", "worker state is offline"),)


def test_unverified_engine_is_never_selected_even_when_installed():
    registry = WorkerRegistry((record("gpu", vram=24 * 1024**3, capabilities=("video",), engines=("wan",)),))
    decision = ComputeBroker(Scheduler(), registry).select_worker(ProductionTask("t", JobRequirements(engines=("wan",))))
    assert decision.selected_worker is None
    assert dict(decision.rejected_workers)["gpu"] == "required engine is not runtime verified"


def test_no_route_is_truthful():
    registry = WorkerRegistry((record("a", vram=4 * 1024**3),))
    decision = ComputeBroker(Scheduler(), registry).select_worker(
        ProductionTask("t", JobRequirements(vram_bytes=16 * 1024**3))
    )
    assert decision.selected_worker is None
    assert decision.reason == "no verified eligible worker"


def test_submit_and_expiry_requeue():
    scheduler = Scheduler()
    registry = WorkerRegistry((record("strong", vram=24 * 1024**3),))
    broker = ComputeBroker(scheduler, registry)
    task = ProductionTask("t", JobRequirements())
    job = broker.submit(task)
    decision, leased = broker.lease(task, now=10, lease_seconds=5)
    assert decision.selected_worker == "strong"
    assert leased is not None and leased.state == JobState.LEASED
    assert broker.release_or_requeue(job.id, 15)
    assert scheduler.snapshot()[0].state == JobState.QUEUED


def test_hardware_requirements_are_enforced_from_observed_gpu_inventory():
    hardware = GpuHostObservation(
        worker_id="gpu",
        driver_version="580.00",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-0", "Observed GPU", 96 * 1024, 0, "0000:01:00.0", "10.0"),),
        topology_text="GPU0 GPU0",
        dcgm_available=True,
        dcgm_version="observed",
        health_json="Overall Health: Healthy",
    )
    registry = WorkerRegistry((record("gpu", vram=96 * 1024**3, hardware=hardware),))
    broker = ComputeBroker(Scheduler(), registry)
    task = ProductionTask(
        "t",
        JobRequirements(
            hardware=HardwareRequirements(
                min_gpu_count=1,
                min_vram_per_gpu_bytes=80 * 1024**3,
                min_compute_capability="9.0",
            )
        ),
    )
    decision = broker.select_worker(task)
    assert decision.selected_worker == "gpu"
    assert decision.selected_gpu_uuids == ("GPU-0",)


def test_topology_sensitive_hardware_is_rejected_without_verified_placement_evidence():
    hardware = GpuHostObservation(
        worker_id="gpu",
        driver_version="580.00",
        cuda_supported_version="13.0",
        gpus=(
            GpuDeviceObservation(0, "GPU-0", "Observed GPU", 96 * 1024, 0, "0000:01:00.0", "10.0"),
            GpuDeviceObservation(1, "GPU-1", "Observed GPU", 96 * 1024, 0, "0000:02:00.0", "10.0"),
        ),
        topology_text="GPU0 GPU1\\nGPU1 GPU0",
        dcgm_available=True,
        dcgm_version="observed",
        health_json="Overall Health: Healthy",
    )
    registry = WorkerRegistry((record("gpu", vram=192 * 1024**3, hardware=hardware),))
    broker = ComputeBroker(Scheduler(), registry)
    task = ProductionTask(
        "t",
        JobRequirements(hardware=HardwareRequirements(min_gpu_count=2, placement=GpuPlacement.SAME_NVLINK_DOMAIN)),
    )
    decision = broker.select_worker(task)
    assert decision.selected_worker is None
    assert dict(decision.rejected_workers)["gpu"] == "observed topology has no verified capability evidence"


def test_lease_binds_the_requested_task_and_exact_gpu_allocation():
    hardware = GpuHostObservation(
        worker_id="gpu",
        driver_version="580.00",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-0", "Observed GPU", 96 * 1024, 0, "0000:01:00.0", "10.0"),),
        topology_text="GPU0 GPU0",
        dcgm_available=True,
        dcgm_version="observed",
        health_json="Overall Health: Healthy",
    )
    scheduler = Scheduler()
    registry = WorkerRegistry((record("gpu", vram=96 * 1024**3, hardware=hardware),))
    broker = ComputeBroker(scheduler, registry)
    requested = ProductionTask("requested", JobRequirements(hardware=HardwareRequirements(min_gpu_count=1)))
    other = ProductionTask("other", JobRequirements(), priority=100)
    broker.submit(requested)
    broker.submit(other)

    decision, leased = broker.lease(requested, now=10, lease_seconds=30)

    assert decision.selected_worker == "gpu"
    assert decision.selected_gpu_uuids == ("GPU-0",)
    assert leased is not None
    assert leased.id == "requested"
    assert leased.allocated_gpu_uuids == ("GPU-0",)


def test_overlapping_gpu_allocation_is_rejected_by_scheduler():
    scheduler = Scheduler()
    resource = ComputeResource("gpu-resource", 16, 32 * 1024**3, gpu_count=1, vram_bytes=96 * 1024**3, logical_slots=4)
    scheduler.submit(Job("first", JobRequirements()))
    scheduler.submit(Job("second", JobRequirements()))

    assert scheduler.choose_on_worker("gpu", resource, 0, now=1, gpu_uuids=("GPU-0",), job_id="first") is not None
    assert scheduler.choose_on_worker("gpu", resource, 0, now=1, gpu_uuids=("GPU-0",), job_id="second") is None


def test_multi_node_task_uses_authoritative_distributed_allocator():
    from studio.distributed_gpu import DistributedGpuAllocator

    def gpu_record(worker_id):
        hardware = GpuHostObservation(
            worker_id=worker_id,
            driver_version="580.00",
            cuda_supported_version="13.0",
            gpus=(
                GpuDeviceObservation(0, f"{worker_id}-GPU-0", "Observed GPU", 96 * 1024, 0, f"0000:{worker_id == 'A' and '01' or '02'}:00.0", "10.0"),
            ),
            topology_text="GPU0 GPU0",
            dcgm_available=True,
            dcgm_version="observed",
            health_json="Overall Health: Healthy",
        )
        return record(worker_id, vram=96 * 1024**3, hardware=hardware)

    registry = WorkerRegistry((gpu_record("A"), gpu_record("B")))
    allocator = DistributedGpuAllocator(registry)
    broker = ComputeBroker(Scheduler(), registry, distributed_allocator=allocator)
    task = ProductionTask(
        "distributed-task",
        JobRequirements(
            hardware=HardwareRequirements(
                min_gpu_count=2,
                min_vram_per_gpu_bytes=80 * 1024**3,
                min_total_vram_bytes=160 * 1024**3,
                placement=GpuPlacement.MULTI_NODE,
                allow_multi_node=True,
            )
        ),
    )

    allocation = broker.reserve_distributed(task, now=100, lease_seconds=60)

    assert allocation.task_id == task.id
    assert allocation.worker_ids == ("A", "B")
    assert allocation.world_size == 2
    assert allocation.gpus_by_worker == (
        ("A", ("A-GPU-0",)),
        ("B", ("B-GPU-0",)),
    )


def test_multi_node_task_never_falls_back_to_single_worker_lease():
    hardware = GpuHostObservation(
        worker_id="gpu",
        driver_version="580.00",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-0", "Observed GPU", 96 * 1024, 0, "0000:01:00.0", "10.0"),),
        topology_text="GPU0 GPU0",
        dcgm_available=True,
        dcgm_version="observed",
        health_json="Overall Health: Healthy",
    )
    scheduler = Scheduler()
    registry = WorkerRegistry((record("gpu", vram=96 * 1024**3, hardware=hardware),))
    broker = ComputeBroker(scheduler, registry)
    task = ProductionTask(
        "distributed-task",
        JobRequirements(
            hardware=HardwareRequirements(
                min_gpu_count=2,
                placement=GpuPlacement.MULTI_NODE,
                allow_multi_node=True,
            )
        ),
    )
    broker.submit(task)

    decision, job = broker.lease(task, now=100, lease_seconds=60)

    assert job is None
    assert decision.selected_worker is None
    assert "multi-node placement requires the distributed group scheduler" in dict(decision.rejected_workers)["gpu"]
    assert scheduler.snapshot()[0].state is JobState.QUEUED


def test_multi_node_reservation_requires_explicit_distributed_allocator():
    broker = ComputeBroker(Scheduler(), WorkerRegistry())
    task = ProductionTask(
        "distributed-task",
        JobRequirements(
            hardware=HardwareRequirements(
                min_gpu_count=2,
                placement=GpuPlacement.MULTI_NODE,
                allow_multi_node=True,
            )
        ),
    )

    with pytest.raises(RuntimeError, match="distributed GPU allocator is not configured"):
        broker.reserve_distributed(task, now=100, lease_seconds=60)
