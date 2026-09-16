#!/usr/bin/env python3
"""Perform real CUDA inference with the official SkyReels V3 R2V pipeline."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from studio.engine_registry import get_catalog_engine
from studio.runtime_verification import verify_engine_runtime
from studio.skyreels_v3_runtime import (
    ENGINE_ID,
    MODEL_REPOSITORY,
    OFFICIAL_REPOSITORY,
    OFFICIAL_SOURCE_REVISION,
    build_skyreels_r2v_command,
)

MODEL_REVISION = "8df04fa97e062099633b366d19a6b0b2dabd5a69"


def require_cuda() -> None:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("SkyReels V3 R2V real runtime verification requires a CUDA GPU")


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
        raise RuntimeError(f"could not read SkyReels source revision: {completed.stderr.strip()}")
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--reference-image", action="append", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--resolution", choices=("480P", "540P", "720P"), default="720P")
    parser.add_argument("--offload", action="store_true")
    parser.add_argument("--low-vram", action="store_true")
    parser.add_argument("--evidence", default="engine-installations/skyreels-v3-r2v-14b/runtime-evidence.json")
    args = parser.parse_args()

    repository = Path(args.repository).expanduser().resolve()
    model_path = Path(args.model_path).expanduser().resolve()
    references = tuple(Path(path).expanduser().resolve() for path in args.reference_image)
    output = Path(args.output).expanduser().resolve()

    if len(references) > 4:
        raise ValueError("SkyReels requires 1 to 4 reference images")
    if any(not path.is_file() or path.stat().st_size == 0 for path in references):
        raise RuntimeError("every SkyReels reference image must be a real non-empty file")
    if git_revision(repository) != OFFICIAL_SOURCE_REVISION:
        raise RuntimeError("SkyReels source revision does not match the pinned official revision")
    if not model_path.is_dir():
        raise RuntimeError(f"SkyReels model directory does not exist: {model_path}")
    if not args.prompt.strip():
        raise ValueError("SkyReels prompt is required")
    require_cuda()

    engine = get_catalog_engine(ENGINE_ID)
    command = build_skyreels_r2v_command(
        python_executable=sys.executable,
        repository=repository,
        model_path=model_path,
        prompt=args.prompt,
        reference_images=references,
        output_token="{output}",
        seed=args.seed,
        duration=args.duration,
        resolution=args.resolution,
        offload=args.offload,
        low_vram=args.low_vram,
    )
    evidence = verify_engine_runtime(
        engine=engine,
        version_command=["git", "-C", str(repository), "rev-parse", "HEAD"],
        execution_command=command,
        checkpoint_path=model_path,
        output_path=output,
        license_source=MODEL_REPOSITORY + "/blob/8df04fa97e062099633b366d19a6b0b2dabd5a69/LICENSE",
        license_evidence=(
            "SkyReels V3 R2V model card states commercial use is supported under the Skywork Community License; "
            "the license also requires compliance with its stated lawful-use and security-review conditions."
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
        "reference_images": [str(path) for path in references],
        "cuda_available": True,
        "verification_mode": "real_model_inference",
        "recorded_at": evidence.recorded_at,
        "promotion_ready": True,
        "note": "Promotion-ready runtime evidence was produced only after real local CUDA generation completed successfully. Commercial-use review remains an explicit production router gate.",
    }
    evidence_path = Path(args.evidence).expanduser().resolve()
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
