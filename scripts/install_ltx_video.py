#!/usr/bin/env python3
"""Install the official LTX-Video source and optionally its pinned 2B checkpoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path("engine-installations") / "ltx-video"
REPOSITORY = ROOT / "LTX-Video"
OFFICIAL_REPOSITORY = "https://github.com/Lightricks/LTX-Video"
EXPECTED_REVISION = "4b2d053057623ddd4d0a1d3e9cd28890e9ef487f"
MODEL_REPOSITORY = "Lightricks/LTX-Video"
MODEL_REVISION = "19560f8b59a58a0431baf39c78cd8a60a86b9c33"
CHECKPOINT = "ltxv-2b-0.9.8-distilled.safetensors"
UPSCALER = "ltxv-spatial-upscaler-0.9.8.safetensors"
CHECKPOINT_SHA256 = "76aa8c4786af752fa6f951947129d5290c3c6c0b2fadcadea6b5e114ae2cad8f"
UPSCALER_SHA256 = "5b076031c6f860db9037a54f3bb819f10bfb5532ea26a6d30062292428a0c208"
MODEL_LICENSE = "LTXV Open Weights License 0.X"
MODEL_LICENSE_SOURCE = "https://huggingface.co/Lightricks/LTX-Video/blob/main/LTX-Video-Open-Weights-License-0.X.txt"


def run(*args: str, cwd: Path | None = None, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False, timeout=timeout)
    if result.stdout:
        print(result.stdout[-6000:], flush=True)
    if result.returncode:
        if result.stderr:
            print(result.stderr[-6000:], flush=True)
        raise RuntimeError(f"command failed: {' '.join(args)}")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-models", action="store_true")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    if REPOSITORY.exists():
        raise RuntimeError(f"refusing to reuse existing LTX installation: {REPOSITORY}")
    run("git", "clone", "--depth", "1", "--branch", "main", OFFICIAL_REPOSITORY, str(REPOSITORY), timeout=1800)
    revision = run("git", "-C", str(REPOSITORY), "rev-parse", "HEAD", timeout=60).stdout.strip()
    if revision != EXPECTED_REVISION:
        raise RuntimeError(f"LTX source revision changed: expected {EXPECTED_REVISION}, got {revision}")
    run("python", "-m", "pip", "install", "--upgrade", "pip", timeout=600)
    run("python", "-m", "pip", "install", "--upgrade", "torch", "--index-url", "https://download.pytorch.org/whl/cpu", timeout=1800)
    run("python", "-m", "pip", "install", "-e", ".[inference]", cwd=REPOSITORY, timeout=3600)
    run("python", "-m", "compileall", "-q", ".", cwd=REPOSITORY, timeout=600)

    models: list[dict[str, object]] = []
    if args.with_models:
        model_root = ROOT / "models"
        run("python", "-m", "pip", "install", "--upgrade", "huggingface_hub[cli]", timeout=1200)
        run("hf", "download", MODEL_REPOSITORY, CHECKPOINT, UPSCALER, "--revision", MODEL_REVISION, "--local-dir", str(model_root), timeout=21600)
        for filename, expected in ((CHECKPOINT, CHECKPOINT_SHA256), (UPSCALER, UPSCALER_SHA256)):
            path = model_root / filename
            if not path.is_file():
                raise RuntimeError(f"required LTX model file missing: {path}")
            actual = sha256(path)
            if actual != expected:
                raise RuntimeError(f"LTX model hash mismatch for {filename}: expected {expected}, got {actual}")
            models.append({"path": str(path), "bytes": path.stat().st_size, "sha256": actual})

    evidence = {
        "engine_id": "ltx-video",
        "source": OFFICIAL_REPOSITORY,
        "repository_revision": revision,
        "model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION,
        "checkpoint": CHECKPOINT,
        "task": "image_to_video",
        "executable": ["python", "scripts/run_ltx_video.py"],
        "models": models,
        "runtime_verified": False,
        "license": MODEL_LICENSE,
        "license_source": MODEL_LICENSE_SOURCE,
        "commercial_use_review_required": True,
        "notes": [
            "Official LTX-Video source is installed at the pinned revision.",
            "The Studio bridge invokes the official ltx_video.inference implementation and binds the requested output path.",
            "The 0.9.8 model weights are governed by the LTXV Open Weights License 0.X, not the repository Apache-2.0 software license.",
            "Installation and compilation are not video-generation verification.",
            "Final CUDA video evidence remains intentionally deferred.",
        ],
    }
    (ROOT / "installation-evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
