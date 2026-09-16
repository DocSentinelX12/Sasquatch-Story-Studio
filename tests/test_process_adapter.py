import os
import sys
from pathlib import Path

from studio.process_adapter import ProcessAdapter
from studio.production import ProductionRequest


def test_process_adapter_executes_real_command_and_records_output(tmp_path: Path):
    output = tmp_path / "render.txt"
    adapter = ProcessAdapter(
        adapter_id="test-process",
        version="1",
        license_name="MIT",
        capabilities=("animation",),
        command=(sys.executable, "-c", "from pathlib import Path; Path(__import__('sys').argv[1]).write_text('rendered', encoding='utf-8')"),
        output_path=str(output),
        working_directory=str(tmp_path),
        verified=True,
    )

    response = adapter.execute(ProductionRequest("animate", {}, "a" * 64, parameters={"output_path": str(output)}))

    assert output.read_text(encoding="utf-8") == "rendered"
    assert response.output_refs == (str(output),)
    assert response.provenance["execution"] == "subprocess"


def test_process_adapter_rejects_unverified_execution(tmp_path: Path):
    adapter = ProcessAdapter(
        adapter_id="unverified",
        version="1",
        license_name="MIT",
        capabilities=("animation",),
        command=(sys.executable, "-c", "raise SystemExit(0)"),
        output_path=str(tmp_path / "out"),
        working_directory=str(tmp_path),
        verified=False,
    )

    try:
        adapter.execute(ProductionRequest("animate", {}, "b" * 64))
    except RuntimeError as exc:
        assert "verified" in str(exc).lower()
    else:
        raise AssertionError("unverified process adapter executed")


def test_process_adapter_binds_leased_gpu_uuids_to_cuda_visibility(tmp_path: Path):
    output = tmp_path / "cuda.txt"
    adapter = ProcessAdapter(
        adapter_id="gpu-process",
        version="1",
        license_name="MIT",
        capabilities=("video_generation",),
        command=(
            sys.executable,
            "-c",
            "from pathlib import Path; import os; Path(__import__('sys').argv[1]).write_text(os.environ.get('CUDA_VISIBLE_DEVICES', ''), encoding='utf-8')",
        ),
        output_path=str(output),
        working_directory=str(tmp_path),
        verified=True,
    )

    response = adapter.execute(
        ProductionRequest(
            "animate",
            {},
            "c" * 64,
            parameters={"output_path": str(output), "gpu_uuids": ("GPU-0", "GPU-7")},
        )
    )

    assert output.read_text(encoding="utf-8") == "GPU-0,GPU-7"
    assert response.provenance["allocated_gpu_uuids"] == ("GPU-0", "GPU-7")
    assert response.provenance["cuda_visible_devices"] == "GPU-0,GPU-7"
