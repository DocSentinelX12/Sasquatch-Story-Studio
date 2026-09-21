"""Real GPU-direct verification boundary.

GPU-direct RDMA is environment and NIC dependent. This module therefore never
infers it from PCIe, RDMA, or topology metadata. A configured physical probe
must execute successfully and emit an explicit success marker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Sequence

from .gpu_infrastructure import probe_nvidia_host


def validate_gpu_direct_output(output: str, success_marker: str) -> bool:
    if not success_marker.strip():
        raise ValueError("GPU-direct success marker is required")
    if success_marker not in output:
        raise RuntimeError("GPU-direct verification output is missing the required success marker")
    return True


def run_gpu_direct_probe(
    command: Sequence[str],
    *,
    success_marker: str,
    timeout_seconds: int = 300,
) -> dict:
    if not command or any(not item for item in command):
        raise ValueError("GPU-direct verification command is required")
    if timeout_seconds < 1:
        raise ValueError("GPU-direct verification timeout must be positive")
    try:
        completed = subprocess.run(
            tuple(command),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"GPU-direct verification executable is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("GPU-direct verification command timed out") from exc

    output = completed.stdout or ""
    if completed.returncode != 0:
        raise RuntimeError(
            f"GPU-direct verification failed with exit code {completed.returncode}: {output.strip()}"
        )
    validate_gpu_direct_output(output, success_marker)

    observation = probe_nvidia_host("local-gpu-direct-verifier")
    return {
        "verification": "real_gpu_direct",
        "recorded_at": int(time.time()),
        "command": list(command),
        "exit_code": completed.returncode,
        "success_marker": success_marker,
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "output": output,
        "gpu_uuids": [gpu.uuid for gpu in observation.gpus],
        "hardware_observation": json.loads(observation.canonical_json()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--command",
        required=True,
        help="Shell-style command for the configured physical GPU-direct probe",
    )
    parser.add_argument("--success-marker", default="GPU_DIRECT_VERIFIED")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    evidence = run_gpu_direct_probe(
        shlex.split(args.command),
        success_marker=args.success_marker,
        timeout_seconds=args.timeout_seconds,
    )
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
