#!/usr/bin/env python3
"""Install the official SkyReels V3 source tree and optional R2V model."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from studio.runtime_verification import sha256_path
from studio.skyreels_v3_runtime import (
    ENGINE_ID,
    MODEL_REPOSITORY,
    OFFICIAL_REPOSITORY,
    OFFICIAL_SOURCE_REVISION,
)

ROOT = Path("engine-installations") / ENGINE_ID
REPOSITORY = ROOT / "SkyReels-V3"
MODEL_ROOT = ROOT / "SkyReels-V3-R2V-14B"
MODEL_REVISION = "8df04fa97e062099633b366d19a6b0b2dabd5a69"


def run(*args: str, cwd: Path | None = None, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    completed = subprocess.run(args, cwd=cwd, check=False, text=True, capture_output=True, timeout=timeout)
    if completed.stdout:
        print(completed.stdout[-8000:], flush=True)
    if completed.returncode != 0:
        if completed.stderr:
            print(completed.stderr[-8000:], file=sys.stderr, flush=True)
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {' '.join(args)}")
    return completed


def git_revision(repository: Path) -> str:
    return run("git", "-C", str(repository), "rev-parse", "HEAD", timeout=60).stdout.strip()


def install_dependencies(repository: Path) -> None:
    requirements = repository / "requirements.txt"
    lines = [line.strip() for line in requirements.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    portable = [line for line in lines if not line.lower().startswith("flash_attn")]
    run(sys.executable, "-m", "pip", "install", *portable, timeout=7200)
    run(sys.executable, "-m", "compileall", "-q", ".", cwd=repository, timeout=900)


def download_model() -> list[Path]:
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    run(sys.executable, "-m", "pip", "install", "--upgrade", "huggingface_hub", timeout=1200)
    run(
        sys.executable,
        "-c",
        (
            "from huggingface_hub import snapshot_download; "
            f"snapshot_download(repo_id='{MODEL_REPOSITORY.rsplit('/', 2)[-2]}/{MODEL_REPOSITORY.rsplit('/', 1)[-1]}', "
            f"revision='{MODEL_REVISION}', local_dir=r'{MODEL_ROOT.resolve()}')"
        ),
        timeout=21600,
    )
    files = [path for path in MODEL_ROOT.rglob("*") if path.is_file()]
    if not files:
        raise RuntimeError("SkyReels model download completed without model files")
    return files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-models", action="store_true")
    args = parser.parse_args()

    ROOT.mkdir(parents=True, exist_ok=True)
    if REPOSITORY.exists():
        raise RuntimeError(f"refusing to reuse an existing SkyReels installation directory: {REPOSITORY}")
    run("git", "clone", "--depth", "1", "--branch", "main", OFFICIAL_REPOSITORY, str(REPOSITORY), timeout=1800)
    revision = git_revision(REPOSITORY)
    if revision != OFFICIAL_SOURCE_REVISION:
        raise RuntimeError(
            f"SkyReels source revision changed unexpectedly: expected {OFFICIAL_SOURCE_REVISION}, observed {revision}"
        )
    install_dependencies(REPOSITORY)

    model_files = download_model() if args.with_models else []
    record = {
        "engine_id": ENGINE_ID,
        "source": OFFICIAL_REPOSITORY,
        "source_revision": revision,
        "model_source": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION,
        "worker_installation_root": str(ROOT.resolve()),
        "repository": str(REPOSITORY.resolve()),
        "model_path": str(MODEL_ROOT.resolve()) if args.with_models else None,
        "executable": [sys.executable, "scripts/run_skyreels_v3_r2v.py"],
        "models": [
            {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_path(path)}
            for path in model_files
        ],
        "runtime_verified": False,
        "notes": [
            "Official SkyReels V3 source repository cloned at the observed upstream revision.",
            "The R2V 14B model is the official Skywork/SkyReels-V3-R2V-14B checkpoint.",
            "The source requirements are installed without flash_attn because the upstream attention module has an explicit PyTorch scaled-dot-product fallback when FlashAttention is unavailable.",
            "Installation evidence does not claim runtime generation verification.",
            "Use scripts/verify_skyreels_v3_runtime.py on a real CUDA host with the complete R2V model before promotion.",
        ],
    }
    evidence_path = ROOT / "installation-evidence.json"
    evidence_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
