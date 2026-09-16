#!/usr/bin/env python3
"""Install the exact LTX-2.5 source runtime without bypassing gated model access."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path("engine-installations") / "ltx-2.5"
REPOSITORY = ROOT / "LTX-2"
OFFICIAL_REPOSITORY = "https://github.com/Lightricks/LTX-2"
EXPECTED_REVISION = "598ab41247a77dbfe29b5186e915bcf4f9040ec7"
MODEL_REPOSITORY = "Lightricks/LTX-2.5"
MODEL_REVISION: str | None = None
MODEL_LICENSE = "LTX-2.x Community License Agreement"
MODEL_LICENSE_SOURCE = "https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x"


def run(*args: str, cwd: Path | None = None, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False, timeout=timeout)
    if result.stdout:
        print(result.stdout[-6000:], flush=True)
    if result.returncode:
        if result.stderr:
            print(result.stderr[-6000:], flush=True)
        raise RuntimeError(f"command failed: {' '.join(args)}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-models", action="store_true")
    args = parser.parse_args()

    ROOT.mkdir(parents=True, exist_ok=True)
    if REPOSITORY.exists():
        raise RuntimeError(f"refusing to reuse existing LTX-2 installation: {REPOSITORY}")

    run("git", "clone", "--depth", "1", "--branch", "v1.3.0", OFFICIAL_REPOSITORY, str(REPOSITORY), timeout=1800)
    revision = run("git", "-C", str(REPOSITORY), "rev-parse", "HEAD", timeout=60).stdout.strip()
    if revision != EXPECTED_REVISION:
        raise RuntimeError(f"LTX-2 source revision changed: expected {EXPECTED_REVISION}, got {revision}")

    run("python", "-m", "pip", "install", "--upgrade", "pip", timeout=600)
    run("python", "-m", "pip", "install", "--upgrade", "uv", timeout=1200)
    run("uv", "sync", cwd=REPOSITORY, timeout=3600)
    run("uv", "run", "python", "-m", "compileall", "-q", "packages", cwd=REPOSITORY, timeout=900)

    if args.with_models:
        raise RuntimeError(
            "LTX-2.5 model download is intentionally blocked until authorized Hugging Face access is "
            "available and the exact gated model revision can be recorded. Do not use an unofficial mirror."
        )

    evidence = {
        "engine_id": "ltx-2.5",
        "source": OFFICIAL_REPOSITORY,
        "source_revision": revision,
        "model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION,
        "runtime_verified": False,
        "checkpoint_verified": False,
        "license_verified": False,
        "license": MODEL_LICENSE,
        "license_source": MODEL_LICENSE_SOURCE,
        "commercial_use_review_required": True,
        "gated_model_access_required": True,
        "executable": ["python", "scripts/run_ltx25.py"],
        "notes": [
            "Official LTX-2 v1.3.0 source is pinned to its exact release commit.",
            "LTX-2.5 weights are gated on Hugging Face and are not downloaded by CI without authorized access.",
            "No third-party or unofficial model mirror is used for provenance or checkpoint verification.",
            "Source installation and compile verification are not model inference verification.",
            "Final CUDA video and synchronized-audio runtime evidence remains deferred.",
        ],
    }
    (ROOT / "installation-evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
