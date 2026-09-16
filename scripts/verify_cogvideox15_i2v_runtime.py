#!/usr/bin/env python3
"""Perform real CUDA inference with the official CogVideoX1.5-5B-I2V pipeline."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from studio.cogvideox15_i2v_runtime import (
    ENGINE_ID,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    OFFICIAL_SOURCE_REVISION,
    build_cogvideox15_i2v_command,
)
from studio.engine_registry import get_catalog_engine
from studio.runtime_verification import verify_engine_runtime


def require_cuda() -> None:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CogVideoX1.5 I2V real runtime verification requires a CUDA GPU")


def git_revision(repository: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"could not read CogVideoX source revision: {completed.stderr.strip()}")
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-frames", type=int, default=81)
    parser.add_argument("--num-inference-steps", type=int, default=50)
    parser.add_argument("--guidance-scale", type=float, default=6.0)
    parser.add_argument("--fps", type=int, default=16)
    parser.add_argument("--sequential-cpu-offload", action="store_true")
    parser.add_argument("--evidence", default="engine-installations/cogvideox1.5-5b-i2v/runtime-evidence.json")
    args = parser.parse_args()

    repository = Path(args.repository).expanduser().resolve()
    model_path = Path(args.model_path).expanduser().resolve()
    image = Path(args.image).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()

    if not image.is_file() or image.stat().st_size == 0:
        raise RuntimeError("CogVideoX reference image must be a real non-empty file")
    if git_revision(repository) != OFFICIAL_SOURCE_REVISION:
        raise RuntimeError("CogVideoX source revision does not match the pinned official revision")
    if not model_path.is_dir() or not any(model_path.iterdir()):
        raise RuntimeError(f"CogVideoX model directory does not exist or is empty: {model_path}")
    if not args.prompt.strip():
        raise ValueError("CogVideoX prompt is required")
    require_cuda()

    engine = get_catalog_engine(ENGINE_ID)
    command = build_cogvideox15_i2v_command(
        python_executable=sys.executable,
        repository=repository,
        model_path=model_path,
        prompt=args.prompt,
        image_path=image,
        output_token="{output}",
        seed=args.seed,
        num_frames=args.num_frames,
        num_inference_steps=args.num_inference_steps,
        guidance_scale=args.guidance_scale,
        fps=args.fps,
        sequential_cpu_offload=args.sequential_cpu_offload,
    )
    evidence = verify_engine_runtime(
        engine=engine,
        version_command=["git", "-C", str(repository), "rev-parse", "HEAD"],
        execution_command=command,
        checkpoint_path=model_path,
        output_path=output,
        license_source=MODEL_REPOSITORY + f"/blob/{MODEL_REVISION}/LICENSE",
        license_evidence=(
            "The pinned CogVideoX1.5-5B-I2V model is released under the CogVideoX License. "
            "Commercial use requires registration and the basic commercial license, with the license's stated terms and limits."
        ),
        recorded_at=int(time.time()),
        working_directory=repository,
        timeout_seconds=21600,
        source_revision=OFFICIAL_SOURCE_REVISION,
    )
    payload = {
        "engine_id": evidence.engine_id,
        "engine_version": evidence.engine_version,
        "executable": evidence.executable,
        "version_observation": evidence.version_observation,
        "source_revision": evidence.source_revision,
        "model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION,
        "checkpoint_path": evidence.checkpoint_path,
        "checkpoint_sha256": evidence.checkpoint_sha256,
        "license_source": evidence.license_source,
        "license_evidence": evidence.license_evidence,
        "runtime_output_sha256": evidence.runtime_output_sha256,
        "runtime_output": str(output),
        "reference_image": str(image),
        "cuda_available": True,
        "verification_mode": "real_model_inference",
        "recorded_at": evidence.recorded_at,
        "promotion_ready": True,
        "note": "Promotion-ready runtime evidence is produced only after real local CUDA generation completes successfully. Commercial-use review remains an explicit production router gate.",
    }
    evidence_path = Path(args.evidence).expanduser().resolve()
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
