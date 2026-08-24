#!/usr/bin/env python3
"""Draft manifest entries for creator source artwork in bulk.

Scans assets/characters/source/ for files that are not yet registered in
assets/asset-manifest.json and drafts `creator_source_artwork` entries with
SHA-256 checksums. Ownership is inferred only from folder location:

- assets/characters/source/<character-slug>/ -> the matching CHAR-* record
- a family's source_folder                  -> that FAMILY-* id

Entries are ALWAYS drafted with approval status "registered". This tool can
never approve, promote, or reclassify anything; only the creator can.

Standard library only.

Usage:
    python3 tools/draft_manifest_entries.py            # dry run (default)
    python3 tools/draft_manifest_entries.py --write    # append entries
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "assets" / "characters" / "source"
MANIFEST_PATH = ROOT / "assets" / "asset-manifest.json"
IGNORED_NAMES = {".gitkeep", "README.md"}
MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slug_to_record_id(records_root: Path) -> dict[str, str]:
    """Map record sourcefolders (`source/<slug>/`) to character ids."""
    mapping: dict[str, str] = {}
    for record_path in sorted(records_root.glob("*.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        location = record.get("source_artwork_location", "")
        match = re.fullmatch(r"assets/characters/source/([a-z0-9-]+)/", str(location))
        cid = record.get("character_id")
        if match and isinstance(cid, str):
            mapping[match.group(1)] = cid
    return mapping


def family_source_slugs(families_root: Path) -> dict[str, str]:
    """Map family intake folders to family ids."""
    mapping: dict[str, str] = {}
    for family_path in sorted(families_root.glob("*.json")):
        try:
            family = json.loads(family_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        folder = family.get("source_folder")
        match = re.fullmatch(r"assets/characters/source/([a-z0-9-]+)/", str(folder)) if folder else None
        fid = family.get("family_id")
        if match and isinstance(fid, str):
            mapping[match.group(1)] = fid
    return mapping


def next_asset_index(existing_ids: list[str]) -> int:
    highest = 0
    for asset_id in existing_ids:
        match = re.fullmatch(r"ASSET-SRC-(\d+)", asset_id)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="append drafted entries to the manifest")
    parser.add_argument("--by", default="creator import (bulk intake)", help="provenance.created_by value")
    args = parser.parse_args()

    if not SOURCE_ROOT.is_dir():
        print("No assets/characters/source/ directory; nothing to do.")
        return 0

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest.setdefault("entries", [])
    registered_paths = {
        str(entry.get("file", {}).get("uri_or_path")) for entry in entries if isinstance(entry, dict)
    }
    existing_ids = [str(entry.get("asset_id")) for entry in entries if isinstance(entry, dict)]

    record_slugs = slug_to_record_id(ROOT / "assets" / "characters" / "records")
    family_slugs = family_source_slugs(ROOT / "assets" / "characters" / "families")

    files = [
        path for path in sorted(SOURCE_ROOT.rglob("*"))
        if path.is_file() and path.name not in IGNORED_NAMES
    ]
    new_files = [path for path in files if str(path.relative_to(ROOT)) not in registered_paths]

    if not new_files:
        print(f"All {len(files)} source file(s) already registered. Nothing to draft.")
        return 0

    index = next_asset_index(existing_ids)
    today = datetime.date.today().isoformat()
    drafted: list[dict[str, object]] = []
    skipped: list[Path] = []

    for path in new_files:
        relative = str(path.relative_to(ROOT))
        top_folder = path.relative_to(SOURCE_ROOT).parts[0]
        entity_id = record_slugs.get(top_folder) or family_slugs.get(top_folder)
        if entity_id is None:
            skipped.append(path)
            continue
        family_id = entity_id if entity_id.startswith("FAMILY-") else None
        asset_id = f"ASSET-SRC-{index:04d}"
        index += 1
        drafted.append({
            "asset_id": asset_id,
            "asset_class": "creator_source_artwork",
            "entity_ids": [entity_id],
            "family_id": family_id,
            "character_version_id": None,
            "purpose": "identity",
            "file": {
                "uri_or_path": relative,
                "media_type": MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                "sha256": sha256_of(path),
            },
            "provenance": {
                "origin": "creator",
                "created_by": args.by,
                "registered_on": today,
                "provider": None,
                "provider_job_id": None,
            },
            "approval": {
                "status": "registered",
                "approved_by": None,
                "approved_on": None,
                "notes": "Bulk-intake draft. NOT approved for provider use until the creator verifies identity and design.",
            },
            "derived_from_asset_ids": [],
        })

    for entry in drafted:
        print(f"DRAFT {entry['asset_id']:16s} -> {entry['entity_ids'][0]:<38s} {entry['file']['uri_or_path']}")
    for path in skipped:
        print(f"SKIP  {path.relative_to(ROOT)} (folder is not mapped to a character record or family)")

    if args.write and drafted:
        entries.extend(drafted)
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"\nAppended {len(drafted)} registered (unapproved) entries to assets/asset-manifest.json.")
        print("Next: run `python3 tools/validate_content.py`, then have the creator verify identifications.")
    elif drafted:
        print(f"\nDry run: {len(drafted)} entries drafted, 0 written. Re-run with --write to append.")
    if skipped:
        print(f"{len(skipped)} file(s) skipped: create a character record or family folder first.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
