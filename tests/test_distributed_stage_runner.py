import sys
from pathlib import Path

from studio.artifact_bridge import ArtifactCommitter, ArtifactLineageStore
from studio.artifacts import ContentAddressedStore
from studio.compute_broker import ComputeBroker
from studio.process_adapter import ProcessAdapter
from studio.production_executor import ProductionWorkerExecutor
from studio.resources import ComputeResource
from studio.scheduler import JobRequirements, Scheduler
from studio.stage_runner import DistributedStageRunner
from studio.worker_fabric import WorkerFabric
from studio.worker_registry import WorkerRecord, WorkerRegistry, WorkerState


def test_stage_runner_reaches_real_process_through_broker_worker_and_artifacts(tmp_path: Path):
    output_name = "shot.bin"
    adapter = ProcessAdapter(
        adapter_id="verification-harness", version="harness", license_name="test-only",
        capabilities=("animation",),
        command=(sys.executable, "-c", "from pathlib import Path; Path('shot.bin').write_bytes(b'end-to-end')"),
        output_path=str(tmp_path / output_name), working_directory=str(tmp_path), verified=True,
    )
    committer = ArtifactCommitter(ContentAddressedStore(tmp_path / "objects"), ArtifactLineageStore(tmp_path / "lineage.sqlite3"))
    executor = ProductionWorkerExecutor(adapter, committer)
    resource = ComputeResource("worker-1", 8, 16 * 1024**3, capabilities=("animation",), installed_engines=("verification-harness",), logical_slots=2, scratch_bytes=4 * 1024**3, power_budget_watts=200)
    registry = WorkerRegistry((WorkerRecord("worker-1", resource, WorkerState.VERIFIED_AVAILABLE),))
    broker = ComputeBroker(Scheduler(), registry, verified_engines=("verification-harness",))
    fabric = WorkerFabric(broker, {"worker-1": executor})
    source_hash = "a" * 64
    runner = DistributedStageRunner(fabric, source_hash, "episode-1", "shot-1")

    address = runner.run_stage(
        stage="animate",
        payload={"engine_id": "verification-harness", "workdir": str(tmp_path), "outputs": [output_name], "args": []},
        requirements=JobRequirements(slots=1, capabilities=("animation",), engines=("verification-harness",)),
        now=100,
        task_id="episode-1-shot-1-animate",
    )

    ref = committer.resolve(address)
    assert Path(ref.path).read_bytes() == b"end-to-end"
    assert broker.scheduler.snapshot()[0].state.value == "completed"
