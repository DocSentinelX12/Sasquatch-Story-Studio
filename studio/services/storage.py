"""File storage for app-managed assets.

Uploads live under assets/studio-uploads/<category>/<yyyy-mm>/<name>.<ext>
(git-ignored binary storage). Files that already exist inside the repository
are referenced in place via `repo_reference` and are NEVER moved or rewritten.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings

UPLOAD_EXTENSIONS: dict[str, str] = {
    # images
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".gif": "image", ".bmp": "image", ".svg": "image", ".avif": "image",
    # video
    ".mp4": "video", ".webm": "video", ".mov": "video", ".mkv": "video",
    # audio
    ".mp3": "audio", ".wav": "audio", ".ogg": "audio", ".flac": "audio",
    ".m4a": "audio", ".aac": "audio", ".opus": "audio",
    # documents
    ".json": "data", ".txt": "data", ".md": "data",
}

MIME_BY_EXT: dict[str, str] = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
    ".svg": "image/svg+xml", ".avif": "image/avif",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
    ".flac": "audio/flac", ".m4a": "audio/mp4", ".aac": "audio/aac",
    ".opus": "audio/opus",
    ".json": "application/json", ".txt": "text/plain", ".md": "text/markdown",
}


@dataclass(frozen=True)
class StoredFile:
    repo_path: str      # repo-relative, forward slashes
    absolute_path: Path
    byte_size: int
    sha256: str
    mime_type: str


def category_slug(category: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", (category or "other").lower()).strip("-")
    return slug or "other"


def safe_extension(filename: str | None) -> str:
    ext = Path(filename or "").suffix.lower()
    return ext if ext in UPLOAD_EXTENSIONS else ""


def guess_mime(filename: str | None) -> str:
    return MIME_BY_EXT.get(safe_extension(filename), "application/octet-stream")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_upload(content: bytes, filename: str, category: str) -> StoredFile:
    """Write an uploaded file into app-managed storage. Never overwrites."""
    ext = safe_extension(filename)
    if not ext:
        raise ValueError(
            f"Unsupported file type '{filename}'. Allowed: {', '.join(sorted(UPLOAD_EXTENSIONS))}"
        )
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    folder = settings.upload_root_absolute / category_slug(category) / month
    folder.mkdir(parents=True, exist_ok=True)

    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(filename).stem).strip("-")[:60] or "file"
    unique = f"{stem}-{uuid.uuid4().hex[:8]}{ext}"
    target = folder / unique
    while target.exists():  # paranoia; uuid makes this near-impossible
        target = folder / f"{stem}-{uuid.uuid4().hex[:12]}{ext}"

    target.write_bytes(content)
    rel = target.relative_to(settings.repo_root)
    return StoredFile(
        repo_path=rel.as_posix(),
        absolute_path=target,
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        mime_type=MIME_BY_EXT[ext],
    )


def resolve_repo_path(repo_path: str) -> Path | None:
    """Resolve a repo-relative path safely (blocks traversal outside the repo)."""
    candidate = (settings.repo_root / repo_path).resolve()
    try:
        candidate.relative_to(settings.repo_root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None
