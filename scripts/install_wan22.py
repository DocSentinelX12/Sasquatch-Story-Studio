#!/usr/bin/env python3
"""Install the official Wan2.2 source tree and record reproducible evidence.

The Studio's ordinary CI runners are CPU-only. Wan2.2's official dependency set
includes flash-attn, which requires a CUDA build environment. We therefore verify
the source/package integration in CPU CI without pretending that CUDA runtime
verification has occurred. The real CUDA dependency/runtime check remains part of
the deferred final video-evidence phase.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path("engine-installations") / "wan2.2"
REPOSITORY = ROOT / "Wan2.2"

OFFICIAL_REPOSITORY = "https://github.com/Wan-Video/Wan2.2"
EXPECTED_REVISION = "42bf4cfaa384bc21833865abc2f9e6c0e67233dc"
MODEL_REPOSITORY = "Wan-AI/Wan2.2-T2V-A14B-Diffusers"


def run(*args: str, cwd: Path | None = None, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(args, cwd=cwd, check=False, text=True, capture_output=True, timeout=timeout)
    if completed.stdout:
        print(completed.stdout[-6000:], flush=True)
    if completed.returncode != 0:
        if completed.stderr:
            print(completed.stderr[-6000:], flush=True)
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {' '.join(args)}")
    return completed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-models", action="store_true", help="Download the selected Wan2.2 model only when explicitly requested.")
    args = parser.parse_args()

    ROOT.mkdir(parents=True, exist_ok=True)
    if REPOSITORY.exists():
        raise RuntimeError(f"refusing to reuse an existing Wan2.2 installation directory: {REPOSITORY}")

    run("git", "clone", "--depth", "1", "--branch", "main", OFFICIAL_REPOSITORY, str(REPOSITORY), timeout=1800)
    revision = run("git", "-C", str(REPOSITORY), "rev-parse", "HEAD", timeout=60).stdout.strip()
    if revision != EXPECTED_REVISION:
        raise RuntimeError(f"Wan2.2 source revision changed unexpectedly: expected {EXPECTED_REVISION}, got {revision}")

    run("python", "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", timeout=600)

    # Wan2.2's setup metadata imports torch while resolving flash-attn. The
    # isolated GitHub runner has no CUDA toolchain, so a normal `pip install .`
    # attempts an impossible flash-attn build. Install the package itself without
    # dependencies for source/package verification; CUDA dependencies are not
    # represented as runtime-verified by this step.
    run("python", "-m", "pip", "install", ".", "--no-deps", cwd=REPOSITORY, timeout=1200)
    run("python", "-m", "compileall", "-q", ".", cwd=REPOSITORY, timeout=600)

    model_evidence: list[dict[str, object]] = []
    if args.with_models:
        model_root = ROOT / "Wan2.2-T2V-A14B-Diffusers"
        run("python", "-m", "pip", "install", "--upgrade", "huggingface_hub[cli]", timeout=1200)
        run("hf", "download", MODEL_REPOSITORY, "--local-dir", str(model_root), timeout=21600)
        for path in sorted(p for p in model_root.rglob("*") if p.is_file()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            model_evidence.append({"path": str(path), "bytes": path.stat().st_size, "sha256": digest})

    evidence = {
        "engine_id": "wan2.2",
        "source": OFFICIAL_REPOSITORY,
        "repository_revision": revision,
        "model_repository": MODEL_REPOSITORY,
        "task": "t2v-A14B",
        "executable": ["python", "generate.py"],
        "models": model_evidence,
        "runtime_verified": False,
        "cuda_dependency_verification": "deferred",
        "notes": [
            "Official Wan2.2 source repository installed at the pinned revision.",
            "Package metadata and source compilation are verified in CPU CI without building flash-attn.",
            "Wan2.2 officially lists flash-attn as a dependency; its CUDA build is intentionally deferred to the final CUDA/video evidence phase.",
            "No source-install success is used as evidence of video-generation runtime success.",
        ],
    }
    evidence_path = ROOT / "installation-evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
