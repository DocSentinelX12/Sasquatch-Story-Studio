#!/usr/bin/env python3
"""Create a repeatable episode workspace from provider-neutral templates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "episodes" / "_templates"
DEVELOPMENT_DIR = ROOT / "episodes" / "in-development"

TEMPLATE_TARGETS = {
    "episode.json": Path("episode.json"),
    "outline.json": Path("story/outline.json"),
    "scene.json": Path("scenes/SC-001.json"),
    "dialogue.json": Path("dialogue/dialogue.json"),
    "storyboard.json": Path("storyboards/storyboard.json"),
    "generation-prompts.json": Path("prompts/generation-prompts.json"),
    "audio-notes.json": Path("audio/audio-notes.json"),
    "continuity-check.json": Path("continuity/continuity-check.json"),
}


def episode_id(value: str) -> str:
    normalized = value.upper()
    if not re.fullmatch(r"EP-\d{3,}", normalized):
        raise argparse.ArgumentTypeError("episode ID must look like EP-002")
    return normalized


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        raise ValueError("title must contain at least one letter or number")
    return slug


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a new in-development Sasquatch Story Studio episode."
    )
    parser.add_argument("episode_id", type=episode_id, help="stable ID, for example EP-002")
    parser.add_argument("title", help="human-readable episode title")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="creation date in YYYY-MM-DD format (defaults to today)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        date.fromisoformat(args.date)
    except ValueError:
        print("error: --date must use YYYY-MM-DD", file=sys.stderr)
        return 2

    slug = slugify(args.title)
    destination = DEVELOPMENT_DIR / f"{args.episode_id}-{slug}"
    if destination.exists():
        print(f"error: destination already exists: {destination.relative_to(ROOT)}", file=sys.stderr)
        return 1

    existing_ids = []
    for episode_file in DEVELOPMENT_DIR.glob("*/episode.json"):
        try:
            existing_ids.append(json.loads(episode_file.read_text(encoding="utf-8")).get("episode_id"))
        except (OSError, json.JSONDecodeError):
            continue
    if args.episode_id in existing_ids:
        print(f"error: {args.episode_id} already exists in episodes/in-development", file=sys.stderr)
        return 1

    replacements = {
        "{{EPISODE_ID}}": args.episode_id,
        "{{TITLE}}": args.title,
        "{{SLUG}}": slug,
        "{{CREATED_DATE}}": args.date,
    }

    rendered: list[tuple[Path, str]] = []
    try:
        for template_name, relative_target in TEMPLATE_TARGETS.items():
            source = TEMPLATE_DIR / template_name
            text = source.read_text(encoding="utf-8")
            for token, value in replacements.items():
                text = text.replace(token, value)
            json.loads(text)
            rendered.append((destination / relative_target, text))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: could not render templates: {exc}", file=sys.stderr)
        return 1

    for target, text in rendered:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    print(f"Created {destination.relative_to(ROOT)}")
    print("Next: replace TODO fields, expand scenes, then run python3 tools/validate_content.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
