"""Repository asset scanner.

Registers files that already exist in the repository (creator source artwork,
approved references, generated tests, episode media...) as `repo_reference`
assets — computing checksums and linking characters by folder — WITHOUT
modifying, moving, renaming, or deleting anything on disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Asset, AssetClass, AssetStatus, AssetStorageMode, AssetVersion, Character, CharacterReference
from .storage import MIME_BY_EXT, sha256_of

# Roots scanned for existing media (repo-relative). The app-managed upload tree
# is skipped because uploads are registered at upload time.
SCAN_ROOTS = ("assets", "episodes")

# Only actual media is registered from the repository — JSON/MD documents are
# canon data, not production assets, and stay untouched by the library.
REPO_MEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".avif", ".tiff",
    ".mp4", ".webm", ".mov", ".mkv", ".avi",
    ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus",
    ".psd", ".clip", ".procreate", ".blend", ".obj", ".fbx", ".glb",
}

# Directories never scanned (dot folders, app runtime data).
SKIP_DIRS = {".git", ".venv", "node_modules", ".data", "web", "studio-uploads"}


@dataclass
class ScanReport:
    scanned_files: int = 0
    registered: int = 0
    already_registered: int = 0
    unsupported: int = 0
    linked_to_characters: int = 0
    family_folders_unmatched: list[str] = field(default_factory=list)
    registered_paths: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scanned_files": self.scanned_files,
            "registered": self.registered,
            "already_registered": self.already_registered,
            "unsupported": self.unsupported,
            "linked_to_characters": self.linked_to_characters,
            "family_folders_unmatched": self.family_folders_unmatched,
            "registered_paths": self.registered_paths[:50],
        }


def _classify(repo_path: str) -> tuple[AssetClass, str]:
    """Classify by location, matching the manifest vocabulary."""
    parts = repo_path.split("/")
    if repo_path.startswith("assets/characters/source/"):
        return AssetClass.CREATOR_SOURCE_ARTWORK, "creator"
    if repo_path.startswith("assets/characters/approved/"):
        return AssetClass.APPROVED_CANON_REFERENCE, "creator"
    if repo_path.startswith("assets/ai-generated-tests/") or repo_path.startswith(
        "assets/characters/generated/"
    ):
        return AssetClass.AI_GENERATED_TEST_MATERIAL, "provider"
    if repo_path.startswith("assets/production/"):
        return AssetClass.PRODUCTION_MATERIAL, "studio"
    # environments/backgrounds/props imported as references count as production material
    return AssetClass.PRODUCTION_MATERIAL, "creator"


def _category_for(repo_path: str) -> str:
    if repo_path.startswith("assets/characters/expressions/"):
        return "expressions"
    if repo_path.startswith("assets/characters/poses/"):
        return "poses"
    if repo_path.startswith("assets/characters/scale/"):
        return "character_references"
    if repo_path.startswith(("assets/characters/reference-sheets/", "assets/characters/approved/")):
        return "character_references"
    if repo_path.startswith("assets/characters/source/"):
        return "characters"
    if repo_path.startswith("assets/characters/"):
        return "characters"
    if repo_path.startswith("assets/locations/"):
        return "environments"
    if repo_path.startswith("assets/environments/"):
        return "environments"
    if repo_path.startswith("assets/props/"):
        return "props"
    if repo_path.startswith("assets/animals/"):
        return "animals"
    if repo_path.startswith("assets/music/"):
        return "music"
    if repo_path.startswith("assets/sound-effects/"):
        return "sound_effects"
    if repo_path.startswith("assets/voice/"):
        return "voice"
    if repo_path.startswith("assets/episodes/"):
        return "video"
    return "other"


def _iter_media_files() -> list[Path]:
    found: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = settings.repo_root / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(settings.repo_root).parts
            if any(part in SKIP_DIRS or part.startswith(".") for part in rel_parts):
                continue
            if path.suffix.lower() in REPO_MEDIA_EXTENSIONS:
                found.append(path)
    return found


def register_repo_assets(session: Session, project_id: int | None = None) -> ScanReport:
    """Register every media file under the scan roots that is not yet tracked."""
    report = ScanReport()
    existing_paths: set[str] = {
        row for row in session.scalars(select(Asset.repo_path)).all() if row
    }
    existing_hashes: set[str] = {
        row for row in session.scalars(select(Asset.sha256)).all() if row
    }

    for absolute in _iter_media_files():
        repo_path = absolute.relative_to(settings.repo_root).as_posix()
        if repo_path in existing_paths:
            report.already_registered += 1
            continue
        report.scanned_files += 1
        checksum = sha256_of(absolute)
        if checksum in existing_hashes:
            report.already_registered += 1
            continue

        asset_class, provenance = _classify(repo_path)
        title = absolute.name
        version = AssetVersion(
            version_number=1,
            storage_mode=AssetStorageMode.REPO_REFERENCE.value,
            repo_path=repo_path,
            sha256=checksum,
            byte_size=absolute.stat().st_size,
            mime_type=MIME_BY_EXT.get(absolute.suffix.lower(), "application/octet-stream"),
            source="repo_scan",
            is_current=True,
        )
        asset = Asset(
            project_id=project_id,
            category=_category_for(repo_path),
            title=title,
            original_filename=title,
            storage_mode=AssetStorageMode.REPO_REFERENCE.value,
            repo_path=repo_path,
            mime_type=MIME_BY_EXT.get(absolute.suffix.lower(), "application/octet-stream"),
            byte_size=absolute.stat().st_size,
            sha256=checksum,
            asset_class=asset_class.value,
            provenance=provenance,
            status=AssetStatus.REGISTERED.value,
            tags=[],
            versions=[version],
        )
        session.add(asset)
        session.flush()
        asset.current_version_id = version.id
        existing_paths.add(repo_path)
        existing_hashes.add(checksum)
        report.registered += 1
        report.registered_paths.append(repo_path)

    session.commit()
    return report


def import_character_references(session: Session, project_id: int) -> dict:
    """Link registered character-folder assets to their characters.

    Assets under assets/characters/source/<folder>/ link to the character whose
    catalog storage folder matches; approved/ folders link as canon references.
    """
    from ..models import CharacterReference  # local import to avoid cycle noise

    characters = session.scalars(
        select(Character).where(Character.project_id == project_id)
    ).all()
    folder_to_character: dict[str, Character] = {}
    for character in characters:
        if character.char_ref:
            slug = character.char_ref.replace("CHAR-", "").lower()
            folder_to_character[slug] = character

    linked = 0
    assets = session.scalars(
        select(Asset).where(Asset.category.in_(["characters", "character_references", "expressions", "poses"]))
    ).all()
    for asset in assets:
        if not asset.repo_path:
            continue
        parts = asset.repo_path.split("/")
        if len(parts) < 5 or parts[0] != "assets" or parts[1] != "characters":
            continue
        subfolder, char_folder = parts[2], parts[3]
        if subfolder not in ("source", "approved", "expressions", "poses", "generated"):
            continue
        character = folder_to_character.get(char_folder)
        if character is None:
            if subfolder == "source":
                # family intake folders (e.g. dark-chocolate-brown-sasquatch-family)
                pass
            continue
        purpose = {
            "source": "primary",
            "approved": "primary",
            "expressions": "expression",
            "poses": "pose",
        }.get(subfolder, "other")
        already = session.scalar(
            select(CharacterReference).where(
                CharacterReference.character_id == character.id,
                CharacterReference.asset_id == asset.id,
            )
        )
        if already is None:
            session.add(
                CharacterReference(
                    character_id=character.id,
                    asset_id=asset.id,
                    purpose=purpose,
                    is_primary=(subfolder in ("source", "approved")),
                )
            )
            linked += 1
    session.commit()
    return {"characters_checked": len(characters), "links_created": linked}
