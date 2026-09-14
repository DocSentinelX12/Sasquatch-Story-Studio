"""First-class Hugging Face Hub integration for creator-owned model provenance.

This module treats Hugging Face as a model/data distribution layer, not an
inference provider. It never calls paid inference APIs. Public repositories work
without credentials; private or gated repositories require an HF_TOKEN supplied
by the worker environment.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HubModelRef:
    repo_id: str
    revision: str | None = None
    filename: str | None = None
    repo_type: str = "model"

    def validate(self) -> None:
        if not self.repo_id or "/" not in self.repo_id:
            raise ValueError("repo_id must be a concrete Hugging Face repository id")
        if self.repo_type not in {"model", "dataset", "space"}:
            raise ValueError("repo_type must be model, dataset, or space")
        if self.revision is not None and not self.revision.strip():
            raise ValueError("revision cannot be empty")
        if self.filename is not None and not self.filename.strip():
            raise ValueError("filename cannot be empty")


@dataclass(frozen=True)
class HubFileEvidence:
    repo_id: str
    repo_type: str
    requested_revision: str | None
    resolved_revision: str
    filename: str
    local_path: str
    bytes: int
    sha256: str
    license: str | None
    private: bool | None
    gated: bool | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hub_token() -> str | bool:
    token = os.environ.get("HF_TOKEN", "").strip()
    return token or False


def _imports() -> tuple[Any, Any, Any]:
    try:
        from huggingface_hub import HfApi, hf_hub_download, snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is not installed; install the official free "
            "huggingface_hub package before using the Hub integration"
        ) from exc
    return HfApi, hf_hub_download, snapshot_download


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(ref: HubModelRef) -> Any:
    """Resolve a concrete Hub repository before downloading anything."""
    ref.validate()
    HfApi, _, _ = _imports()
    api = HfApi(token=_hub_token())
    return api.repo_info(
        repo_id=ref.repo_id,
        revision=ref.revision,
        repo_type=None if ref.repo_type == "model" else ref.repo_type,
        files_metadata=True,
    )


def download_file(ref: HubModelRef, destination: Path) -> HubFileEvidence:
    """Download one file at an immutable resolved revision and hash it."""
    ref.validate()
    if not ref.filename:
        raise ValueError("filename is required for download_file")
    info = resolve(ref)
    resolved_revision = getattr(info, "sha", None)
    if not resolved_revision:
        raise RuntimeError(f"Hugging Face did not return a repository commit SHA for {ref.repo_id}")
    _, hf_hub_download, _ = _imports()
    destination.mkdir(parents=True, exist_ok=True)
    local_path = Path(
        hf_hub_download(
            repo_id=ref.repo_id,
            filename=ref.filename,
            repo_type=None if ref.repo_type == "model" else ref.repo_type,
            revision=resolved_revision,
            local_dir=destination,
            token=_hub_token(),
        )
    )
    if not local_path.is_file() or local_path.stat().st_size == 0:
        raise RuntimeError(f"Hugging Face download did not produce a non-empty file: {local_path}")
    license_value = None
    card_data = getattr(info, "card_data", None)
    if card_data is not None:
        license_value = getattr(card_data, "license", None)
        if license_value is None and isinstance(card_data, dict):
            license_value = card_data.get("license")
    return HubFileEvidence(
        repo_id=ref.repo_id,
        repo_type=ref.repo_type,
        requested_revision=ref.revision,
        resolved_revision=resolved_revision,
        filename=ref.filename,
        local_path=str(local_path.resolve()),
        bytes=local_path.stat().st_size,
        sha256=_sha256(local_path),
        license=license_value,
        private=getattr(info, "private", None),
        gated=getattr(info, "gated", None),
    )


def download_snapshot(ref: HubModelRef, destination: Path, *, allow_patterns: list[str] | None = None) -> dict[str, Any]:
    """Download a repository snapshot pinned to its resolved Hub commit."""
    ref.validate()
    info = resolve(ref)
    resolved_revision = getattr(info, "sha", None)
    if not resolved_revision:
        raise RuntimeError(f"Hugging Face did not return a repository commit SHA for {ref.repo_id}")
    _, _, snapshot_download = _imports()
    destination.mkdir(parents=True, exist_ok=True)
    local_path = Path(
        snapshot_download(
            repo_id=ref.repo_id,
            repo_type=None if ref.repo_type == "model" else ref.repo_type,
            revision=resolved_revision,
            local_dir=destination,
            allow_patterns=allow_patterns,
            token=_hub_token(),
        )
    )
    files = []
    for path in sorted(p for p in local_path.rglob("*") if p.is_file() and ".cache" not in p.parts):
        files.append({"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": _sha256(path)})
    if not files:
        raise RuntimeError(f"Hugging Face snapshot was empty: {local_path}")
    return {
        "repo_id": ref.repo_id,
        "repo_type": ref.repo_type,
        "requested_revision": ref.revision,
        "resolved_revision": resolved_revision,
        "local_path": str(local_path.resolve()),
        "files": files,
        "private": getattr(info, "private", None),
        "gated": getattr(info, "gated", None),
    }


def write_evidence(path: Path, evidence: HubFileEvidence | dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = evidence.to_dict() if isinstance(evidence, HubFileEvidence) else evidence
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
