"""Real single-node NCCL collective verification."""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from .gpu_infrastructure import probe_nvidia_host


def validate_nccl_result(*, exit_code: int, observed_sum: float, expected_sum: float) -> bool:
    if exit_code != 0:
        raise RuntimeError(f"NCCL collective verification failed with exit code {exit_code}")
    if observed_sum != expected_sum:
        raise RuntimeError(
            f"NCCL collective result mismatch: observed {observed_sum}, expected {expected_sum}"
        )
    return True


def _torch_device_uuid(torch, index: int) -> str:
    value = getattr(torch.cuda.get_device_properties(index), "uuid", None)
    if value is None:
        raise RuntimeError(f"PyTorch did not expose a UUID for CUDA device {index}")
    return str(value)


def _nccl_worker(rank: int, world_size: int, init_method: str, result_dir: str) -> None:
    import torch
    import torch.distributed as dist

    torch.cuda.set_device(rank)
    runtime_uuid = _torch_device_uuid(torch, rank)
    dist.init_process_group(
        backend="nccl",
        init_method=init_method,
        rank=rank,
        world_size=world_size,
    )
    try:
        tensor = torch.ones(1, device=f"cuda:{rank}")
        dist.all_reduce(tensor, op=dist.ReduceOp.SUM)
        torch.cuda.synchronize(rank)
        observed = float(tensor.item())
        validate_nccl_result(
            exit_code=0,
            observed_sum=observed,
            expected_sum=float(world_size),
        )
        Path(result_dir, f"rank-{rank}.json").write_text(
            json.dumps(
                {"rank": rank, "gpu_uuid": runtime_uuid, "observed_sum": observed},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    finally:
        dist.destroy_process_group()


def verify_nccl_runtime(*, output_path: str | Path) -> dict:
    try:
        import torch
        import torch.distributed as dist
    except ImportError as exc:
        raise RuntimeError("PyTorch with torch.distributed is required for NCCL verification") from exc

    if not bool(torch.cuda.is_available()):
        raise RuntimeError("CUDA must be available before NCCL verification")

    observation = probe_nvidia_host("local-nccl-verifier")
    world_size = observation.gpu_count
    actual = int(torch.cuda.device_count())
    if world_size < 2:
        raise RuntimeError("real NCCL verification requires at least two visible GPUs")
    if actual != world_size:
        raise RuntimeError(
            f"NCCL CUDA device count mismatch: observed {world_size}, runtime {actual}"
        )
    if not dist.is_nccl_available():
        raise RuntimeError("PyTorch was not built with NCCL support")

    observed_uuids = [gpu.uuid for gpu in observation.gpus]
    runtime_uuids = [_torch_device_uuid(torch, index) for index in range(world_size)]
    if runtime_uuids != observed_uuids:
        raise RuntimeError(
            "NCCL runtime device identity mismatch: "
            f"observed {observed_uuids}, runtime {runtime_uuids}"
        )

    with tempfile.TemporaryDirectory(prefix="sasquatch-nccl-") as result_dir:
        rendezvous = Path(result_dir) / "rendezvous"
        init_method = f"file://{rendezvous}"
        torch.multiprocessing.spawn(
            _nccl_worker,
            args=(world_size, init_method, result_dir),
            nprocs=world_size,
            join=True,
        )
        rank_results = [
            json.loads(Path(result_dir, f"rank-{rank}.json").read_text(encoding="utf-8"))
            for rank in range(world_size)
        ]

    if len(rank_results) != world_size:
        raise RuntimeError("NCCL verification did not produce one result per rank")
    if any(item["observed_sum"] != float(world_size) for item in rank_results):
        raise RuntimeError("NCCL verification produced an inconsistent collective result")
    if [item["gpu_uuid"] for item in rank_results] != observed_uuids:
        raise RuntimeError("NCCL rank-to-GPU identity mapping does not match physical observation")

    evidence = {
        "verification": "real_nccl_single_node",
        "recorded_at": int(time.time()),
        "backend": "nccl",
        "world_size": world_size,
        "gpu_uuids": observed_uuids,
        "torch_version": str(torch.__version__),
        "torch_cuda_version": str(torch.version.cuda),
        "results": rank_results,
        "hardware_observation": json.loads(observation.canonical_json()),
    }
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    verify_nccl_runtime(output_path=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
