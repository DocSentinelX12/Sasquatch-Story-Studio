#!/usr/bin/env python3
"""Install the official HunyuanVideo-1.5 source tree and optionally its model set."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from studio.hunyuan_runtime import ENGINE_ID, OFFICIAL_REPOSITORY
from studio.runtime_verification import sha256_path

ROOT = Path("engine-installations") / ENGINE_ID
REPOSITORY = ROOT / "HunyuanVideo-1.5"
MODEL_ROOT = ROOT / "ckpts"


def run(*args: str, cwd: Path | None = None, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    completed = subprocess.run(args, cwd=cwd, check=False, text=True, capture_output=True, timeout=timeout)
    if completed.stdout:
        print(completed.stdout[-8000:], flush=True)
    if completed.returncode != 0:
        if completed.stderr:
            print(completed.stderr[-8000:], flush=True)
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {' '.join(args)}")
    return completed


def git_revision(repository: Path) -> str:
    return run("git", "-C", str(repository), "rev-parse", "HEAD", timeout=60).stdout.strip()


def install_dependencies(repository: Path) -> None:
    run("python", "-m", "pip", "install", "--upgrade", "pip", timeout=600)
    run("python", "-m", "pip", "install", "-r", "requirements.txt", timeout=3600, cwd=repository)
    run("python", "-m", "pip", "install", "tencentcloud-sdk-python", timeout=1200)
    run("python", "-m", "compileall", "-q", ".", cwd=repository, timeout=600)


def download_models() -> list[Path]:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("--with-models requires HF_TOKEN because the official I2V vision encoder requires approved Hugging Face access")
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    run("python", "-m", "pip", "install", "--upgrade", "huggingface_hub[cli]", "modelscope", timeout=1200)
    run("hf", "download", "tencent/HunyuanVideo-1.5", "--local-dir", str(MODEL_ROOT), timeout=21600)
    run("hf", "download", "Qwen/Qwen2.5-VL-7B-Instruct", "--local-dir", str(MODEL_ROOT / "text_encoder" / "llm"), timeout=7200)
    run("hf", "download", "google/byt5-small", "--local-dir", str(MODEL_ROOT / "text_encoder" / "byt5-small"), timeout=3600)
    run("modelscope", "download", "--model", "AI-ModelScope/Glyph-SDXL-v2", "--local_dir", str(MODEL_ROOT / "text_encoder" / "Glyph-SDXL-v2"), timeout=7200)
    run("hf", "download", "black-forest-labs/FLUX.1-Redux-dev", "--local-dir", str(MODEL_ROOT / "vision_encoder" / "siglip"), "--token", token, timeout=7200)
    return [p for p in MODEL_ROOT.rglob("*") if p.is_file()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-models", action="store_true")
    args = parser.parse_args()

    ROOT.mkdir(parents=True, exist_ok=True)
    if REPOSITORY.exists():
        raise RuntimeError(f"refusing to reuse an existing Hunyuan installation directory: {REPOSITORY}")
    run("git", "clone", "--depth", "1", OFFICIAL_REPOSITORY, str(REPOSITORY), timeout=1800)
    install_dependencies(REPOSITORY)

    model_files = download_models() if args.with_models else []
    revision = git_revision(REPOSITORY)
    record = {
        "engine_id": ENGINE_ID,
        "source": OFFICIAL_REPOSITORY,
        "worker_installation_root": str(ROOT.resolve()),
        "repository_revision": revision,
        "executable": ["torchrun", "--nproc_per_node=1", "generate.py"],
        "models": [
            {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_path(path)}
            for path in model_files
        ],
        "runtime_verified": False,
        "notes": [
            "Official HunyuanVideo-1.5 source repository cloned and dependencies installed.",
            "Installation evidence does not claim runtime generation verification.",
            "Use scripts/verify_hunyuanvideo15_runtime.py on a real CUDA host with the complete model directory before promotion.",
        ],
    }
    evidence_path = ROOT / "installation-evidence.json"
    evidence_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
