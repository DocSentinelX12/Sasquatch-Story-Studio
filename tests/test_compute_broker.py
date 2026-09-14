from studio.compute_broker import ComputeBroker, ProductionTask
from studio.resources import ComputeResource
from studio.scheduler import JobRequirements, JobState, Scheduler
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


def record(worker_id, *, vram, capabilities=(), engines=(), state=WorkerState.VERIFIED_AVAILABLE):
    return WorkerRecord(
        worker_id,
        ComputeResource(
            worker_id + "-resource", 16, 32 * 1024**3, gpu_count=1,
            vram_bytes=vram, capabilities=capabilities, installed_engines=engines,
            logical_slots=4, scratch_bytes=100 * 1024**3, power_budget_watts=500,
        ), state=state,
    )


def test_routes_only_to_observed_capabilities():
    registry = WorkerRegistry((
        record("small", vram=8 * 1024**3, capabilities=("video",), engines=("wan",)),
        record("strong", vram=24 * 1024**3, capabilities=("video", "cuda"), engines=("wan",)),
    ))
    broker = ComputeBroker(Scheduler(), registry)
    task = ProductionTask("shot-1", JobRequirements(vram_bytes=16 * 1024**3, capabilities=("cuda",), engines=("wan",)))
    decision = broker.select_worker(task)
    assert decision.selected_worker == "strong"
    assert dict(decision.rejected_workers)["small"] == "insufficient VRAM"


def test_unavailable_worker_is_never_selected():
    registry = WorkerRegistry((record("offline", vram=32 * 1024**3, state=WorkerState.OFFLINE),))
    decision = ComputeBroker(Scheduler(), registry).select_worker(ProductionTask("t", JobRequirements()))
    assert decision.selected_worker is None
    assert decision.rejected_workers == (("offline", "worker state is offline"),)


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
