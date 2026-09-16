"""Install and record provenance for CogVideoX1.5-5B-I2V without claiming runtime inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("engine-installations") / "cogvideox1.5-5b-i2v"
REPOSITORY_URL = "https://github.com/zai-org/CogVideo"
MODEL_REPOSITORY = "zai-org/CogVideoX1.5-5B-I2V"
OFFICIAL_SOURCE_REVISION = "7a1af7154511e0ce4e4be8d62faa8c5e5a3532d2"
MODEL_REVISION = "e724b279e89c204de20b66d8c09317a5d0d1b6f6"


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_requirements(repository: Path) -> None:
    requirements = repository / "requirements.txt"
    if not requirements.is_file():
        raise SystemExit("Official CogVideo requirements.txt is missing")
    lines = requirements.read_text(encoding="utf-8").splitlines()
    filtered = [
        line for line in lines
        if line.strip() and not line.lstrip().startswith("#")
        and not line.lower().startswith(("torch", "torchvision"))
    ]
    run(sys.executable, "-m", "pip", "install", "torch", "torchvision", "--index-url", "https://download.pytorch.org/whl/cpu")
    run(sys.executable, "-m", "pip", "install", *filtered)


def download_model(model_root: Path) -> tuple[int, str]:
    from huggingface_hub import snapshot_download

    model_root.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_REPOSITORY,
        revision=MODEL_REVISION,
        local_dir=str(model_root),
        local_dir_use_symlinks=False,
    )
    files = [path for path in model_root.rglob("*") if path.is_file()]
    if not files:
        raise SystemExit("Pinned CogVideoX model revision produced no local files")
    total_bytes = sum(path.stat().st_size for path in files)
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(str(path.relative_to(model_root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return total_bytes, digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-models", action="store_true")
    args = parser.parse_args()

    ROOT.mkdir(parents=True, exist_ok=True)
    repository = ROOT / "CogVideo"
    model_root = ROOT / "CogVideoX1.5-5B-I2V"

    if not repository.exists():
        run("git", "clone", "--no-tags", "--depth", "1", REPOSITORY_URL, str(repository))
    observed_revision = run("git", "-C", str(repository), "rev-parse", "HEAD")
    if observed_revision != OFFICIAL_SOURCE_REVISION:
        run("git", "-C", str(repository), "fetch", "--depth", "1", "origin", OFFICIAL_SOURCE_REVISION)
        run("git", "-C", str(repository), "checkout", OFFICIAL_SOURCE_REVISION)
        observed_revision = run("git", "-C", str(repository), "rev-parse", "HEAD")
    if observed_revision != OFFICIAL_SOURCE_REVISION:
        raise SystemExit(f"CogVideo source revision mismatch: {observed_revision}")

    install_requirements(repository)
    run(sys.executable, "-m", "compileall", "-q", str(repository / "inference"))

    model_bytes = 0
    model_digest = None
    if args.with_models:
        run(sys.executable, "-m", "pip", "install", "huggingface_hub>=0.35.0")
        model_bytes, model_digest = download_model(model_root)

    evidence = {
        "engine_id": "cogvideox1.5-5b-i2v",
        "source": REPOSITORY_URL,
        "source_revision": observed_revision,
        "model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION,
        "worker_installation_root": str(ROOT.resolve()),
        "model_path": str(model_root.resolve()) if args.with_models else None,
        "model_bytes": model_bytes,
        "model_tree_sha256": model_digest,
        "executable": str((repository / "inference" / "cli_demo.py").resolve()),
        "runtime_verified": False,
        "notes": [
            "Official CogVideoX source and requirements were used.",
            "The selected model is CogVideoX1.5-5B-I2V and accepts an image plus prompt.",
            "Installation evidence does not claim successful video generation.",
            "Real CUDA inference is deferred to the final runtime-evidence phase.",
            "Commercial use requires the CogVideoX basic commercial license and its stated conditions.",
        ],
    }
    (ROOT / "installation-evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
