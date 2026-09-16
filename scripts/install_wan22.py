#!/usr/bin/env python3
"""Install the official Wan2.2 source tree and record reproducible evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
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

    run("python", "-m", "pip", "install", "--upgrade", "pip", timeout=600)
    run("python", "-m", "pip", "install", ".", cwd=REPOSITORY, timeout=3600)
    run("python", "-m", "compileall", "-q", ".", cwd=REPOSITORY, timeout=600)

    model_evidence: list[dict[str, object]] = []
    if args.with_models:
        model_root = ROOT / "Wan2.2-T2V-A14B-Diffusers"
        run("python", "-m", "pip", "install", "--upgrade", "huggingface_hub[cli]", timeout=1200)
        run("hf", "download", MODEL_REPOSITORY, "--local-dir", str(model_root), timeout=21600)
        files = [p for p in model_root.rglob("*") if p.is_file()]
        for path in files:
            import hashlib
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
        "notes": [
            "Official Wan2.2 source repository installed at the pinned revision.",
            "Installation and source compilation do not claim video-generation verification.",
            "Final CUDA video evidence remains intentionally deferred.",
        ],
    }
    evidence_path = ROOT / "installation-evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
