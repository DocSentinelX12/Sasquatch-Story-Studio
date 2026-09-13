"""YouTube package generation without performing external publishing."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path


@dataclass(frozen=True)
class YouTubePackage:
    title: str
    description: str
    tags: tuple[str, ...]
    transcript_path: str | None = None
    thumbnail_path: str | None = None
    content_warning: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_youtube_package(*, title: str, description: str, tags: list[str], transcript_path: str | None = None, thumbnail_path: str | None = None) -> YouTubePackage:
    if not title.strip():
        raise ValueError("YouTube title is required")
    if not description.strip():
        raise ValueError("YouTube description is required")
    normalized = tuple(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
    return YouTubePackage(title, description, normalized, transcript_path, thumbnail_path)


def write_youtube_package(package: YouTubePackage, destination: str | Path) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(package.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
