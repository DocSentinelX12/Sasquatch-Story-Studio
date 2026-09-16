#!/usr/bin/env python3
"""Perform a real HunyuanVideo-1.5 inference and emit promotion-ready evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from studio.engine_registry import get_catalog_engine
from studio.hunyuan_runtime import ENGINE_ID, OFFICIAL_REPOSITORY, build_hunyuan_command
from studio.runtime_verification import verify_engine_runtime

LICENSE_SOURCE = f"{OFFICIAL_REPOSITORY}/blob/main/LICENSE"
LICENSE_EVIDENCE = (
    "Official Tencent Hunyuan Community License Agreement observed; "
    "the Territory excludes the European Union, United Kingdom, and South Korea; "
    "the studio keeps commercial-use review and territory restrictions enforced."
)
OFFICIAL_SSH_ORIGIN = "git@github.com:Tencent-Hunyuan/HunyuanVideo-1.5"


def _git_revision(repository: Path) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repository), "rev-parse", "HEAD"),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"could not observe Hunyuan repository revision: {detail}")
    revision = completed.stdout.strip()
    if not revision:
        raise RuntimeError("Hunyuan repository revision observation was empty")
    return revision


def _git_origin(repository: Path) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repository), "remote", "get-url", "origin"),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"could not observe Hunyuan repository origin: {detail}")
    origin = completed.stdout.strip().rstrip("/")
    if origin.endswith(".git"):
        origin = origin[:-4]
    if origin not in {OFFICIAL_REPOSITORY, OFFICIAL_SSH_ORIGIN}:
        raise RuntimeError(f"Hunyuan repository origin is not the official source: {origin}")
    return origin


def require_cuda() -> None:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("Hunyuan runtime verification requires PyTorch in the execution environment") from exc
    if not torch.cuda.is_available():
        raise RuntimeError("HunyuanVideo-1.5 runtime verification requires an NVIDIA CUDA GPU")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-path", type=Path)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--prompt",
        default="A stylized 2D forest character takes three playful steps through a moonlit clearing.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()

    repository = args.repository.expanduser().resolve()
    model_path = args.model_path.expanduser().resolve()
    output = args.output.expanduser().resolve()
    evidence_path = args.evidence.expanduser().resolve()

    if not repository.is_dir():
        raise RuntimeError(f"Hunyuan repository does not exist: {repository}")
    if not (repository / "generate.py").is_file():
        raise RuntimeError(f"Hunyuan generator is missing: {repository / 'generate.py'}")
    if not model_path.is_dir():
        raise RuntimeError(f"Hunyuan model path must be a real model directory: {model_path}")
    if args.image_path is not None:
        image_path = args.image_path.expanduser().resolve()
        if not image_path.is_file() or image_path.stat().st_size == 0:
            raise RuntimeError(f"Hunyuan reference image is missing or empty: {image_path}")
    if args.timeout_seconds < 1:
        raise ValueError("timeout-seconds must be positive")

    require_cuda()
    engine = get_catalog_engine(ENGINE_ID)
    origin = _git_origin(repository)
    revision = _git_revision(repository)
    command = build_hunyuan_command(
        torchrun_executable="torchrun",
        repository=repository,
        model_path=model_path,
        prompt=args.prompt,
        image_path=args.image_path,
        output_token="{output}",
        seed=args.seed,
    )
    evidence = verify_engine_runtime(
        engine=engine,
        version_command=("git", "-C", str(repository), "rev-parse", "HEAD"),
        execution_command=command,
        checkpoint_path=model_path,
        output_path=output,
        license_source=LICENSE_SOURCE,
        license_evidence=f"{LICENSE_EVIDENCE} Official source origin observed as {origin}.",
        recorded_at=int(time.time()),
        working_directory=repository,
        timeout_seconds=args.timeout_seconds,
        source_revision=revision,
    )

    payload = evidence.to_record().__dict__
    payload["model_path_type"] = "directory"
    payload["cuda_available"] = True
    payload["generator"] = "torchrun --nproc_per_node=1 generate.py"
    payload["verification_mode"] = "real_model_inference"
    payload["reference_image"] = str(args.image_path.expanduser().resolve()) if args.image_path else None
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
