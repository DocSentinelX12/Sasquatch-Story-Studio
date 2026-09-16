#!/usr/bin/env python3
"""Perform a real HunyuanVideo-1.5 inference and emit promotion-ready evidence.

This script never marks the engine verified on installation alone. It requires a
real Linux/CUDA runtime, a real local HunyuanVideo-1.5 model directory, and the
actual upstream generator. The resulting evidence can be promoted only through
the existing evidence registry workflow.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from studio.engine_registry import get_catalog_engine
from studio.runtime_verification import verify_engine_runtime

ENGINE_ID = "hunyuanvideo-1.5"
LICENSE_SOURCE = "https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5/blob/main/LICENSE"
LICENSE_EVIDENCE = (
    "Official Tencent Hunyuan Community License Agreement observed; "
    "studio production routing remains commercial-use-review gated and territory restricted."
)


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


def require_cuda() -> None:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("Hunyuan runtime verification requires PyTorch in the execution environment") from exc
    if not torch.cuda.is_available():
        raise RuntimeError("HunyuanVideo-1.5 runtime verification requires an NVIDIA CUDA GPU")


def build_execution_command(
    *,
    python_executable: str,
    prompt: str,
    model_path: Path,
    output_token: str,
    seed: int,
) -> tuple[str, ...]:
    return (
        python_executable,
        "generate.py",
        "--prompt",
        prompt,
        "--image_path",
        "none",
        "--resolution",
        "480p",
        "--aspect_ratio",
        "16:9",
        "--seed",
        str(seed),
        "--num_inference_steps",
        "4",
        "--video_length",
        "9",
        "--sr",
        "false",
        "--rewrite",
        "false",
        "--offloading",
        "true",
        "--output_path",
        output_token,
        "--model_path",
        str(model_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
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
    if not model_path.exists():
        raise RuntimeError(f"Hunyuan model path does not exist: {model_path}")
    if args.timeout_seconds < 1:
        raise ValueError("timeout-seconds must be positive")

    require_cuda()

    engine = get_catalog_engine(ENGINE_ID)
    revision = _git_revision(repository)
    command = build_execution_command(
        python_executable=sys.executable,
        prompt=args.prompt,
        model_path=model_path,
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
        license_evidence=LICENSE_EVIDENCE,
        recorded_at=int(time.time()),
        working_directory=repository,
        timeout_seconds=args.timeout_seconds,
    )

    payload = evidence.to_record().__dict__
    payload["model_revision"] = revision
    payload["model_path_type"] = "directory"
    payload["cuda_available"] = True
    payload["generator"] = "generate.py"
    payload["verification_mode"] = "real_model_inference"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
