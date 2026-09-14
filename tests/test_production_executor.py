import json
import sys
from pathlib import Path

from studio.artifact_bridge import ArtifactCommitter, ArtifactLineageStore
from studio.artifacts import ContentAddressedStore
from studio.process_adapter import ProcessAdapter
from studio.production_executor import ProductionWorkerExecutor
from studio.resources import ComputeResource
from studio.scheduler import JobRequirements
from studio.worker import WorkerTask, WorkerResultState


def test_production_worker_executor_runs_real_process_and_commits_artifact(tmp_path: Path):
    output_name = "render.bin"
    command = (sys.executable, "-c", "from pathlib import Path; Path('render.bin').write_bytes(b'worker-render')")
    adapter = ProcessAdapter(
        adapter_id="verification-harness",
        version="harness",
        license_name="test-only",
        capabilities=("animation",),
        command=command,
        output_path=str(tmp_path / output_name),
        working_directory=str(tmp_path),
        verified=True,
    )
    committer = ArtifactCommitter(ContentAddressedStore(tmp_path / "objects"), ArtifactLineageStore(tmp_path / "lineage.sqlite3"))
    executor = ProductionWorkerExecutor(adapter, committer)
    source_hash = "a" * 64
    task = WorkerTask(
        "task-1", "episode-1", "animate", "shot-1", (), (),
        JobRequirements(slots=1, capabilities=("animation",)),
        canonical_source_hash=source_hash,
        payload_json=json.dumps({"workdir": str(tmp_path), "outputs": [output_name], "args": []}),
    )
    result = executor.execute(task)
    assert result.state == WorkerResultState.COMPLETED
    assert result.output_refs[0].startswith("sha256:")
    assert committer.resolve(result.output_refs[0]).size_bytes == len(b"worker-render")


def test_production_worker_executor_rejects_missing_request_data(tmp_path: Path):
    adapter = ProcessAdapter(
        adapter_id="verification-harness", version="harness", license_name="test-only",
        capabilities=("animation",), command=(sys.executable, "-c", "print('unused')"),
        output_path=str(tmp_path / "out"), working_directory=str(tmp_path), verified=True,
    )
    committer = ArtifactCommitter(ContentAddressedStore(tmp_path / "objects"), ArtifactLineageStore(tmp_path / "lineage.sqlite3"))
    result = ProductionWorkerExecutor(adapter, committer).execute(
        WorkerTask("task-2", "episode-1", "animate", "shot-1", (), (), JobRequirements())
    )
    assert result.state == WorkerResultState.REJECTED
