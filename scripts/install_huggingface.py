#!/usr/bin/env python3
"""Install and verify the official Hugging Face Hub client without paid services."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, TypeVar

EVIDENCE = Path("engine-installations/huggingface/installation-evidence.json")
# This repository/file is taken directly from the official Hugging Face download
# documentation and is intentionally tiny, so installation verification does not
# pull a large model checkpoint.
VERIFY_REPO = "google/pegasus-xsum"
VERIFY_FILE = "config.json"
RETRY_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 2.0
T = TypeVar("T")


def retry_operation(
    operation: Callable[[], T],
    *,
    attempts: int = RETRY_ATTEMPTS,
    delay_seconds: float = RETRY_DELAY_SECONDS,
    is_retryable: Callable[[Exception], bool],
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    if attempts < 1:
        raise ValueError("retry attempts must be at least one")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt >= attempts or not is_retryable(exc):
                raise
            sleep_fn(delay_seconds * (2 ** (attempt - 1)))
    assert last_error is not None
    raise last_error


def is_transient_huggingface_error(exc: Exception) -> bool:
    # huggingface_hub uses httpx for its network transport. Keep the dependency
    # import local so this script remains importable before installation.
    try:
        import httpx
    except ImportError:
        return False
    return isinstance(exc, httpx.RequestError)


def run(*args: str, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    result = subprocess.run(args, check=False, text=True, capture_output=True, timeout=timeout)
    if result.stdout:
        print(result.stdout[-8000:], flush=True)
    if result.returncode:
        if result.stderr:
            print(result.stderr[-8000:], file=sys.stderr, flush=True)
        raise RuntimeError(f"command failed with exit code {result.returncode}: {' '.join(args)}")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    run(sys.executable, "-m", "pip", "install", "huggingface_hub>=1.0,<2", timeout=1200)
    version = run(sys.executable, "-c", "import huggingface_hub; print(huggingface_hub.__version__)").stdout.strip()
    run("hf", "--version")

    from huggingface_hub import HfApi, hf_hub_download

    token = os.environ.get("HF_TOKEN", "").strip() or False
    api = HfApi(token=token)
    info = retry_operation(
        lambda: api.model_info(VERIFY_REPO, files_metadata=True, token=token),
        is_retryable=is_transient_huggingface_error,
    )
    if not getattr(info, "sha", None):
        raise RuntimeError("Hugging Face verification repository did not return a commit SHA")

    root = EVIDENCE.parent / "verification-download"
    root.mkdir(parents=True, exist_ok=True)
    path = Path(
        retry_operation(
            lambda: hf_hub_download(
                repo_id=VERIFY_REPO,
                filename=VERIFY_FILE,
                revision=info.sha,
                local_dir=root,
                token=token,
            ),
            is_retryable=is_transient_huggingface_error,
        )
    )
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Hugging Face verification download is missing or empty: {path}")

    siblings = {getattr(item, "rfilename", ""): getattr(item, "size", None) for item in (getattr(info, "siblings", None) or [])}
    expected_size = siblings.get(VERIFY_FILE)
    if expected_size is not None and expected_size != path.stat().st_size:
        raise RuntimeError(f"Downloaded Hugging Face file size mismatch: expected {expected_size}, got {path.stat().st_size}")

    record = {
        "integration": "huggingface-hub",
        "source": "https://huggingface.co/",
        "package": "huggingface_hub",
        "package_version": version,
        "cli_verified": True,
        "api_verified": True,
        "download_verified": True,
        "verification_repo": VERIFY_REPO,
        "verification_file": VERIFY_FILE,
        "resolved_revision": info.sha,
        "downloaded_path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "private": getattr(info, "private", None),
        "gated": getattr(info, "gated", None),
        "paid_service_used": False,
        "runtime_generation_verified": False,
        "note": "Hub installation and public model-file acquisition are verified. This is not inference/runtime-generation verification.",
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
