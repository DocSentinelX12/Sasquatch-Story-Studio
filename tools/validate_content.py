#!/usr/bin/env python3
"""Validate canon references, episode packages, and non-negotiable rules.

The validator uses only Python's standard library. JSON Schema files remain the
portable interchange contracts; these checks add repository-specific semantics.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BAREFOOT_EXCLUSIONS = ("shoes", "socks", "boots", "sandals", "slippers", "skates", "cleats", "footwear")
VALID_STATUSES = {"concept", "outline", "script", "storyboard", "prompt-ready", "production", "completed"}
ASSET_CLASSES = {
    "creator_source_artwork",
    "approved_canon_reference",
    "ai_generated_test_material",
    "final_approved_production_asset",
}
IDENTITY_REFERENCE_CLASSES = {"creator_source_artwork", "approved_canon_reference"}
AGE_GROUPS = {"infant", "toddler", "child", "preteen", "teen", "young_adult", "adult", "senior", "unconfirmed"}
VISUAL_AUTHORITY_SENTENCE = (
    "Creator-provided character artwork is authoritative. AI must preserve the "
    "established character designs and must not redesign characters."
)


@dataclass
class Issue:
    path: Path
    message: str

    def render(self) -> str:
        try:
            display = self.path.relative_to(ROOT)
        except ValueError:
            display = self.path
        return f"{display}: {self.message}"


class Validation:
    def __init__(self) -> None:
        self.errors: list[Issue] = []
        self.warnings: list[Issue] = []
        self.documents: dict[Path, dict[str, Any]] = {}

    @property
    def json_count(self) -> int:
        return len(self.documents)

    def error(self, path: Path, message: str) -> None:
        self.errors.append(Issue(path, message))

    def warning(self, path: Path, message: str) -> None:
        self.warnings.append(Issue(path, message))

    def load(self, path: Path) -> dict[str, Any]:
        if path in self.documents:
            return self.documents[path]
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.error(path, f"invalid JSON: {exc}")
            self.documents[path] = {}
            return {}
        if not isinstance(value, dict):
            self.error(path, "top-level JSON value must be an object")
            self.documents[path] = {}
            return {}
        self.documents[path] = value
        return value


def duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    return repeated


def require_keys(check: Validation, path: Path, data: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        if key not in data:
            check.error(path, f"missing required field {key!r}")


def check_schema_path(check: Validation, path: Path, data: dict[str, Any]) -> None:
    schema = data.get("$schema")
    if isinstance(schema, str) and not schema.startswith("http"):
        resolved = (path.parent / schema).resolve()
        if not resolved.is_file():
            check.error(path, f"$schema does not resolve to a file: {schema}")


def validate() -> Validation:
    check = Validation()

    # Parse every JSON file, including templates and schemas, before semantic checks.
    for path in sorted(ROOT.rglob("*.json")):
        check.load(path)

    series_path = ROOT / "series-bible" / "series.json"
    series = check.load(series_path)
    check_schema_path(check, series_path, series)
    require_keys(check, series_path, series, ("series_id", "canon_version", "protagonist_id", "non_negotiables"))
    rules = {item.get("rule_id"): item for item in series.get("non_negotiables", []) if isinstance(item, dict)}
    barefoot_rule = rules.get("RULE-BAREFOOT", {})
    if "always barefoot" not in str(barefoot_rule.get("rule", "")).lower():
        check.error(series_path, "RULE-BAREFOOT must explicitly say all characters are always barefoot")
    authority_rule = rules.get("RULE-CREATOR-VISUAL-AUTHORITY", {})
    if VISUAL_AUTHORITY_SENTENCE.lower() not in str(authority_rule.get("rule", "")).lower():
        check.error(
            series_path,
            "RULE-CREATOR-VISUAL-AUTHORITY must preserve the exact creator-art authority statement",
        )

    manifest_path = ROOT / "assets" / "asset-manifest.json"
    manifest = check.load(manifest_path)
    check_schema_path(check, manifest_path, manifest)
    require_keys(
        check,
        manifest_path,
        manifest,
        ("manifest_id", "visual_authority", "barefoot_rule", "character_catalog_path", "family_registry_path", "asset_classes", "entries"),
    )
    if VISUAL_AUTHORITY_SENTENCE.lower() not in str(manifest.get("visual_authority", "")).lower():
        check.error(manifest_path, "visual_authority must contain the creator-art authority statement")
    if "always barefoot" not in str(manifest.get("barefoot_rule", "")).lower():
        check.error(manifest_path, "barefoot_rule must explicitly say all characters are always barefoot")
    declared_classes = {
        item.get("class") for item in manifest.get("asset_classes", []) if isinstance(item, dict)
    }
    if declared_classes != ASSET_CLASSES:
        check.error(manifest_path, "asset_classes must declare exactly the four immutable asset classes")
    if manifest.get("character_catalog_path") != "assets/characters/character-catalog.json":
        check.error(manifest_path, "character_catalog_path must point at assets/characters/character-catalog.json")
    if manifest.get("family_registry_path") != "assets/characters/families/":
        check.error(manifest_path, "family_registry_path must point at assets/characters/families/")

    asset_entries: dict[str, dict[str, Any]] = {}
    for entry in manifest.get("entries", []):
        if not isinstance(entry, dict):
            check.error(manifest_path, "every asset manifest entry must be an object")
            continue
        asset_id = entry.get("asset_id")
        if not isinstance(asset_id, str) or not re.fullmatch(r"ASSET-[A-Z0-9-]+", asset_id):
            check.error(manifest_path, f"invalid asset_id {asset_id!r}")
            continue
        if asset_id in asset_entries:
            check.error(manifest_path, f"duplicate asset_id {asset_id}")
        asset_entries[asset_id] = entry
        asset_class = entry.get("asset_class")
        if asset_class not in ASSET_CLASSES:
            check.error(manifest_path, f"{asset_id} has unknown asset_class {asset_class!r}")
        file_data = entry.get("file", {})
        uri_or_path = str(file_data.get("uri_or_path", "")) if isinstance(file_data, dict) else ""
        checksum = str(file_data.get("sha256", "")) if isinstance(file_data, dict) else ""
        if not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
            check.error(manifest_path, f"{asset_id} must have a 64-character SHA-256 checksum")
        if uri_or_path.startswith("assets/") and not (ROOT / uri_or_path).is_file():
            check.error(manifest_path, f"{asset_id} points to missing local file {uri_or_path}")
        provenance = entry.get("provenance", {})
        approval = entry.get("approval", {})
        origin = provenance.get("origin") if isinstance(provenance, dict) else None
        approval_status = approval.get("status") if isinstance(approval, dict) else None
        if asset_class == "creator_source_artwork":
            if origin != "creator":
                check.error(manifest_path, f"{asset_id} creator source must have creator origin")
            if "/source/" not in uri_or_path:
                check.error(manifest_path, f"{asset_id} creator source must live under a source directory")
        elif asset_class == "approved_canon_reference":
            if origin != "approved_derivative":
                check.error(manifest_path, f"{asset_id} canon reference must have approved_derivative origin")
            if approval_status != "approved_for_reference":
                check.error(manifest_path, f"{asset_id} canon reference must be approved_for_reference")
            if not entry.get("derived_from_asset_ids"):
                check.error(manifest_path, f"{asset_id} canon reference must link its creator source")
        elif asset_class == "ai_generated_test_material":
            if origin != "ai_generation":
                check.error(manifest_path, f"{asset_id} AI test must have ai_generation origin")
            if approval_status in {"approved_for_reference", "approved_for_production"}:
                check.error(manifest_path, f"{asset_id} AI test cannot carry an approved asset status")
        elif asset_class == "final_approved_production_asset":
            if approval_status != "approved_for_production":
                check.error(manifest_path, f"{asset_id} final production asset must be approved_for_production")
        family_link = entry.get("family_id")
        if family_link is not None and not re.fullmatch(r"FAMILY-[A-Z0-9-]+", str(family_link)):
            check.error(manifest_path, f"{asset_id} has invalid family_id {family_link!r}")
        version_link = entry.get("character_version_id")
        if version_link is not None and not re.fullmatch(r"VER-[A-Z0-9-]+", str(version_link)):
            check.error(manifest_path, f"{asset_id} has invalid character_version_id {version_link!r}")
        if asset_class == "ai_generated_test_material" and ("/source/" in uri_or_path or "/approved/" in uri_or_path):
            check.error(manifest_path, f"{asset_id} AI test material must never live under a source/ or approved/ tree")
    for asset_id, entry in asset_entries.items():
        parent_ids = entry.get("derived_from_asset_ids", [])
        for parent_id in parent_ids:
            if parent_id not in asset_entries:
                check.error(manifest_path, f"{asset_id} derives from unknown asset {parent_id}")
        if entry.get("asset_class") == "approved_canon_reference":
            parent_classes = {
                asset_entries[parent_id].get("asset_class")
                for parent_id in parent_ids
                if parent_id in asset_entries
            }
            if "ai_generated_test_material" in parent_classes:
                check.error(manifest_path, f"{asset_id} canon reference cannot derive from an AI test")
            if "creator_source_artwork" not in parent_classes:
                check.error(manifest_path, f"{asset_id} canon reference must derive directly from creator source artwork")

    registered_paths = {
        str(entry.get("file", {}).get("uri_or_path", "")) for entry in asset_entries.values()
    }

    characters: dict[str, dict[str, Any]] = {}
    for path in sorted((ROOT / "series-bible" / "characters").glob("*.json")):
        data = check.load(path)
        check_schema_path(check, path, data)
        require_keys(check, path, data, ("character_id", "name", "personality", "visual", "performance", "continuity_locks"))
        cid = data.get("character_id")
        if not isinstance(cid, str) or not re.fullmatch(r"CHAR-[A-Z0-9-]+", cid):
            check.error(path, "character_id must match CHAR-[A-Z0-9-]+")
            continue
        if cid in characters:
            check.error(path, f"duplicate character_id {cid}")
        characters[cid] = data
        visual = data.get("visual", {})
        footwear_rule = str(visual.get("footwear_rule", "")).lower() if isinstance(visual, dict) else ""
        if "always barefoot" not in footwear_rule:
            check.error(path, "visual.footwear_rule must explicitly say always barefoot")
        if not isinstance(visual, dict) or visual.get("authority") != "creator_source_artwork":
            check.error(path, "visual.authority must be creator_source_artwork")
        if not isinstance(visual, dict) or visual.get("description_status") != "deferred_until_creator_artwork_import":
            check.error(path, "unverified written visual descriptions must remain deferred until creator art import")
        if not any("barefoot" in str(lock).lower() for lock in data.get("continuity_locks", [])):
            check.error(path, "continuity_locks must include the barefoot requirement")
        if not any("creator-provided artwork is authoritative" in str(lock).lower() for lock in data.get("continuity_locks", [])):
            check.error(path, "continuity_locks must include creator-art authority")
        visual_record = data.get("visual_reference_record")
        if not isinstance(visual_record, str) or not (ROOT / visual_record).is_file():
            check.error(path, "visual_reference_record must resolve to a character visual record")
        if data.get("reference_asset_ids"):
            check.error(path, "character card reference_asset_ids must remain empty; link assets in the visual record")

    # --- Scalable character catalog: the index tying every reference to a character ---
    catalog_entries: dict[str, dict[str, Any]] = {}
    catalog_path = ROOT / "assets" / "characters" / "character-catalog.json"
    if not catalog_path.is_file():
        check.error(catalog_path, "missing scalable character catalog")
    else:
        catalog = check.load(catalog_path)
        check_schema_path(check, catalog_path, catalog)
        require_keys(check, catalog_path, catalog, ("catalog_id", "visual_authority", "barefoot_rule", "entries"))
        if catalog.get("catalog_id") != "CHARACTER-CATALOG-SASQUATCH-STORY-STUDIO":
            check.error(catalog_path, "catalog_id must be CHARACTER-CATALOG-SASQUATCH-STORY-STUDIO")
        if VISUAL_AUTHORITY_SENTENCE.lower() not in str(catalog.get("visual_authority", "")).lower():
            check.error(catalog_path, "catalog must carry the creator-art authority statement")
        if "always barefoot" not in str(catalog.get("barefoot_rule", "")).lower():
            check.error(catalog_path, "catalog must carry the barefoot rule")
        for entry in catalog.get("entries", []):
            if not isinstance(entry, dict):
                check.error(catalog_path, "catalog entries must be objects")
                continue
            cid = entry.get("character_id")
            if not isinstance(cid, str) or not re.fullmatch(r"CHAR-[A-Z0-9-]+", cid):
                check.error(catalog_path, f"invalid catalog character_id {cid!r}")
                continue
            if cid in catalog_entries:
                check.error(catalog_path, f"duplicate catalog entry for {cid}")
            catalog_entries[cid] = entry
            status = entry.get("catalog_status")
            if status not in {"active_record", "registered_shell", "retired"}:
                check.error(catalog_path, f"{cid} has invalid catalog_status {status!r}")
            if entry.get("character_kind") not in {"person", "animal"}:
                check.error(catalog_path, f"{cid} has invalid character_kind (pets/animals use 'animal')")
            if not str(entry.get("species", "")).strip():
                check.error(catalog_path, f"{cid} needs a species (use 'unconfirmed' until creator art verifies it)")
            storage = entry.get("storage", {})
            if isinstance(storage, dict):
                for key in ("source_folder", "approved_folder"):
                    folder = storage.get(key)
                    if folder is not None and not (ROOT / str(folder)).is_dir():
                        check.error(catalog_path, f"{cid} storage.{key} does not exist: {folder}")
            record_path = entry.get("record_path")
            if status == "registered_shell":
                if record_path is not None:
                    check.error(catalog_path, f"shell entry {cid} must keep record_path null until the creator identifies the character")
                if cid in characters:
                    check.error(catalog_path, f"{cid} cannot be both a registered_shell and a series-bible character")
            elif status == "active_record":
                if cid not in characters:
                    check.error(catalog_path, f"active catalog entry {cid} has no series-bible character card")
                elif entry.get("character_name") != characters[cid].get("name"):
                    check.error(catalog_path, f"catalog name for {cid} does not match the series-bible card")
                if not isinstance(record_path, str) or not (ROOT / record_path).is_file():
                    check.error(catalog_path, f"active catalog entry {cid} needs a record_path that resolves")
    for cid in characters:
        if cid not in catalog_entries:
            check.error(catalog_path, f"character {cid} is missing from the character catalog")

    # --- Family registry: groups keep parent/child/pet relationships connected ---
    families: dict[str, dict[str, Any]] = {}
    families_root = ROOT / "assets" / "characters" / "families"
    for path in sorted(families_root.glob("*.json")):
        family = check.load(path)
        check_schema_path(check, path, family)
        require_keys(check, path, family, (
            "family_id", "display_name", "family_kind", "status",
            "member_character_ids", "parent_character_ids", "child_character_ids",
            "pet_character_ids", "source_folder",
        ))
        fid = family.get("family_id")
        if not isinstance(fid, str) or not re.fullmatch(r"FAMILY-[A-Z0-9-]+", fid):
            check.error(path, "family_id must match FAMILY-[A-Z0-9-]+")
            continue
        if fid in families:
            check.error(path, f"duplicate family_id {fid}")
        families[fid] = family
        if family.get("status") not in {"active", "awaiting_import", "partially_identified", "retired"}:
            check.error(path, f"{fid} has unknown status {family.get('status')!r}")
        members = family.get("member_character_ids", [])
        for cid in members:
            if cid not in catalog_entries:
                check.error(path, f"{fid} member {cid} is not in the character catalog")
        for key in ("parent_character_ids", "child_character_ids"):
            for cid in family.get(key, []):
                if cid not in members:
                    check.error(path, f"{fid} {key} entry {cid} must also be listed in member_character_ids")
        for cid in family.get("pet_character_ids", []):
            pet_entry = catalog_entries.get(cid)
            if pet_entry is None:
                check.error(path, f"{fid} pet {cid} is not in the character catalog")
            elif pet_entry.get("character_kind") != "animal":
                check.error(path, f"{fid} pet {cid} must have catalog character_kind 'animal'; pets are full characters")
        folder = family.get("source_folder")
        if folder is not None:
            family_dir = ROOT / str(folder)
            if not family_dir.is_dir():
                check.error(path, f"{fid} source_folder does not exist: {folder}")
            else:
                for image in family_dir.glob("**/*"):
                    if image.is_file() and image.name not in {".gitkeep", "README.md"}:
                        relative = str(image.relative_to(ROOT))
                        if relative not in registered_paths:
                            check.error(path, f"family source file is not registered in manifest: {relative}")
    for cid, entry in catalog_entries.items():
        family_id = entry.get("family_id")
        if family_id is not None and family_id not in families:
            check.error(catalog_path, f"catalog entry {cid} references unknown family {family_id}")
    for asset_id, entry in asset_entries.items():
        family_link = entry.get("family_id")
        if family_link is not None and family_link not in families:
            check.error(manifest_path, f"{asset_id} references unknown family {family_link}")

    visual_records: dict[str, dict[str, Any]] = {}
    record_paths: dict[str, Path] = {}
    visual_records_root = ROOT / "assets" / "characters" / "records"
    for path in sorted(visual_records_root.glob("*.json")):
        record = check.load(path)
        check_schema_path(check, path, record)
        require_keys(
            check,
            path,
            record,
            (
                "character_id", "character_name", "species", "character_kind", "family_id",
                "age_group", "approximate_age", "canon_role", "personality", "relationships",
                "parent_character_ids", "child_character_ids", "pet_character_ids",
                "caretaker_character_ids", "character_versions",
                "visual_authority", "source_artwork_location", "source_artwork_asset_ids",
                "approved_reference_images", "turnaround_reference", "expression_reference",
                "pose_reference", "scale_reference", "clothing_reference", "color_reference",
                "animation_notes", "master_generation_prompt", "negative_prompt",
                "continuity_rules", "provider_neutral_reference_support", "approval_status",
            ),
        )
        cid = record.get("character_id")
        if cid not in characters:
            check.error(path, f"visual record references unknown character {cid}")
            continue
        if cid in visual_records:
            check.error(path, f"duplicate visual reference record for {cid}")
        visual_records[cid] = record
        record_paths[cid] = path
        card = characters[cid]
        expected_record_path = str(path.relative_to(ROOT))
        if card.get("visual_reference_record") != expected_record_path:
            check.error(path, f"character card does not link this record: {expected_record_path}")
        if record.get("character_name") != card.get("name"):
            check.error(path, "character_name must match the series-bible character card")
        if VISUAL_AUTHORITY_SENTENCE.split(" AI must", 1)[0].lower() not in str(record.get("visual_authority", "")).lower():
            check.error(path, "visual_authority must establish creator artwork as authoritative")
        source_location = record.get("source_artwork_location")
        source_dir = ROOT / str(source_location)
        if not isinstance(source_location, str) or not source_dir.is_dir():
            check.error(path, "source_artwork_location must resolve to an existing character source directory")

        # --- Scalable identity metadata ---
        if not str(record.get("species", "")).strip():
            check.error(path, "species is required; use 'unconfirmed' until creator artwork verifies it")
        if record.get("character_kind") not in {"person", "animal"}:
            check.error(path, "character_kind must be 'person' or 'animal' (pets/animals are full characters)")
        record_family = record.get("family_id")
        if record_family is not None:
            if not re.fullmatch(r"FAMILY-[A-Z0-9-]+", str(record_family)):
                check.error(path, f"invalid family_id {record_family!r}")
            elif record_family not in families:
                check.error(path, f"family_id {record_family} is not in assets/characters/families/")
        if record.get("age_group") not in AGE_GROUPS:
            check.error(path, "age_group must be a supported band or 'unconfirmed'")
        known_characters = set(characters) | set(catalog_entries)
        for field in ("parent_character_ids", "child_character_ids", "pet_character_ids", "caretaker_character_ids"):
            ids = record.get(field)
            if not isinstance(ids, list):
                check.error(path, f"{field} must be an array of CHAR-* ids")
                continue
            for other_id in ids:
                if not isinstance(other_id, str) or not re.fullmatch(r"CHAR-[A-Z0-9-]+", other_id):
                    check.error(path, f"{field} contains invalid id {other_id!r}")
                elif other_id not in known_characters:
                    check.error(path, f"{field} references unknown character {other_id}")
                elif other_id == cid:
                    check.error(path, f"{field} must not contain the character itself")
        if record.get("character_kind") == "animal":
            if not record.get("caretaker_character_ids") and not record_family:
                check.warning(path, f"{cid} is an animal with no caretakers or family; attach pets to their people")
        catalog_entry = catalog_entries.get(cid)
        if catalog_entry is None:
            check.error(path, f"{cid} is missing from assets/characters/character-catalog.json")
        else:
            if catalog_entry.get("record_path") != str(path.relative_to(ROOT)):
                check.error(path, "catalog record_path must point at this record")
            if catalog_entry.get("family_id") != record_family:
                check.error(path, "catalog family_id must match the record family_id")
            counts = catalog_entry.get("asset_counts", {})
            if isinstance(counts, dict):
                expected_counts = {"source_artwork": 0, "approved_references": 0, "generated_tests": 0}
                for asset in asset_entries.values():
                    if cid in asset.get("entity_ids", []):
                        cls = asset.get("asset_class")
                        if cls == "creator_source_artwork":
                            expected_counts["source_artwork"] += 1
                        elif cls == "approved_canon_reference":
                            expected_counts["approved_references"] += 1
                        elif cls == "ai_generated_test_material":
                            expected_counts["generated_tests"] += 1
                for key, want in expected_counts.items():
                    if counts.get(key) != want:
                        check.error(path, f"catalog asset_counts.{key} is {counts.get(key)!r} but the manifest has {want}")
            if record_family is not None:
                family = families.get(record_family, {})
                if cid not in family.get("member_character_ids", []):
                    check.error(path, f"{record_family} must list {cid} in member_character_ids")

        # --- Canonical versions (ages / story periods) ---
        versions = record.get("character_versions")
        if not isinstance(versions, list) or not versions:
            check.error(path, "character_versions must contain at least one version")
        else:
            version_ids: list[str] = []
            primary_count = 0
            for version in versions:
                if not isinstance(version, dict):
                    check.error(path, "each character version must be an object")
                    continue
                vid = version.get("version_id")
                if not isinstance(vid, str) or not re.fullmatch(r"VER-[A-Z0-9-]+", vid):
                    check.error(path, f"invalid version_id {vid!r}")
                else:
                    version_ids.append(vid)
                if version.get("age_group") not in AGE_GROUPS:
                    check.error(path, f"version {vid} has invalid age_group")
                if not str(version.get("story_period", "")).strip():
                    check.error(path, f"version {vid} needs a canonical story_period")
                if version.get("is_primary") is True:
                    primary_count += 1
                for asset_id in version.get("reference_asset_ids", []):
                    entry = asset_entries.get(asset_id)
                    if entry is None:
                        check.error(path, f"version {vid} references unknown manifest asset {asset_id}")
                    elif entry.get("asset_class") == "ai_generated_test_material":
                        check.error(path, f"version {vid} cannot use AI test {asset_id} as a reference")
            if len(version_ids) != len(set(version_ids)):
                check.error(path, "duplicate character version ids")
            if primary_count != 1:
                check.error(path, "exactly one character version must be marked primary")
        relationship_ids = {
            relation.get("character_id") for relation in record.get("relationships", [])
            if isinstance(relation, dict)
        }
        unknown_relationships = sorted(cid for cid in relationship_ids if cid not in characters)
        if unknown_relationships:
            check.error(path, f"relationships reference unknown characters: {', '.join(unknown_relationships)}")

        source_ids = record.get("source_artwork_asset_ids", [])
        approved_ids = record.get("approved_reference_images", [])
        slot_ids = []
        for slot_name in (
            "turnaround_reference", "expression_reference", "pose_reference",
            "scale_reference", "clothing_reference", "color_reference",
        ):
            slot = record.get(slot_name, {})
            if isinstance(slot, dict) and slot.get("asset_id"):
                slot_ids.append(slot["asset_id"])
        support = record.get("provider_neutral_reference_support", {})
        ordered_ids = support.get("ordered_asset_ids", []) if isinstance(support, dict) else []
        linked_ids = list(source_ids) + list(approved_ids) + slot_ids + list(ordered_ids)
        for asset_id in linked_ids:
            entry = asset_entries.get(asset_id)
            if entry is None:
                check.error(path, f"references unknown manifest asset {asset_id}")
                continue
            if cid not in entry.get("entity_ids", []):
                check.error(path, f"asset {asset_id} is not linked to {cid} in the manifest")
            if entry.get("asset_class") == "ai_generated_test_material":
                check.error(path, f"AI test {asset_id} cannot be a character reference")
        for asset_id in source_ids:
            entry = asset_entries.get(asset_id, {})
            if entry and entry.get("asset_class") != "creator_source_artwork":
                check.error(path, f"source artwork asset {asset_id} has the wrong class")
        for asset_id in approved_ids + slot_ids:
            entry = asset_entries.get(asset_id, {})
            if entry and entry.get("asset_class") != "approved_canon_reference":
                check.error(path, f"approved reference {asset_id} has the wrong class")
        if isinstance(support, dict):
            accepted = set(support.get("accepted_asset_classes", []))
            if accepted != IDENTITY_REFERENCE_CLASSES:
                check.error(path, "provider reference support must allow exactly creator source and approved canon references")
            if support.get("allow_ai_generated_test_material") is not False:
                check.error(path, "provider reference support must reject AI-generated test material")
            if support.get("missing_reference_behavior") != "block_and_request_creator_review":
                check.error(path, "missing references must block and request creator review")
        prompt_text = str(record.get("master_generation_prompt", "")).lower()
        negative_text = str(record.get("negative_prompt", "")).lower()
        if "creator" not in prompt_text or "source of truth" not in prompt_text or "barefoot" not in prompt_text:
            check.error(path, "master_generation_prompt must lock creator authority and barefoot continuity")
        missing_negative = [term for term in (*BAREFOOT_EXCLUSIONS, "redesign", "reinterpret") if term not in negative_text]
        if missing_negative:
            check.error(path, f"negative_prompt is missing: {', '.join(missing_negative)}")
        source_files = [
            file for file in source_dir.glob("**/*")
            if file.is_file() and file.name not in {".gitkeep", "README.md"}
        ] if source_dir.is_dir() else []
        for source_file in source_files:
            relative = str(source_file.relative_to(ROOT))
            if relative not in registered_paths:
                check.error(path, f"creator source file is not registered in manifest: {relative}")

    missing_visual_records = sorted(set(characters) - set(visual_records))
    if missing_visual_records:
        check.error(visual_records_root, f"missing visual records: {', '.join(missing_visual_records)}")

    # Parent/child relationships must be symmetric once both sides have records.
    for cid, record in visual_records.items():
        for child_id in record.get("child_character_ids", []):
            child_record = visual_records.get(child_id)
            if child_record and cid not in child_record.get("parent_character_ids", []):
                check.error(record_paths[cid], f"{child_id} must list {cid} in parent_character_ids")
        for pet_id in record.get("pet_character_ids", []):
            pet_record = visual_records.get(pet_id)
            if pet_record and pet_record.get("character_kind") != "animal":
                check.error(record_paths[cid], f"pet {pet_id} must have character_kind 'animal' in its record")
            if pet_record and cid not in pet_record.get("caretaker_character_ids", []):
                check.error(record_paths[cid], f"pet {pet_id} must list {cid} in caretaker_character_ids")

    # Manifest entries that pin a canonical version must pin one that exists.
    for asset_id, entry in asset_entries.items():
        version_id = entry.get("character_version_id")
        if not version_id:
            continue
        owners = [cid for cid in entry.get("entity_ids", []) if cid in visual_records]
        if not owners:
            check.error(manifest_path, f"{asset_id} pins version {version_id} but is not linked to a character with a record")
            continue
        known_versions = {
            version.get("version_id")
            for cid in owners
            for version in visual_records[cid].get("character_versions", [])
            if isinstance(version, dict)
        }
        if version_id not in known_versions:
            check.error(manifest_path, f"{asset_id} pins version {version_id} that is not in the linked character records")

    locations: dict[str, dict[str, Any]] = {}
    for path in sorted((ROOT / "series-bible" / "locations").glob("*.json")):
        data = check.load(path)
        check_schema_path(check, path, data)
        require_keys(check, path, data, ("location_id", "name", "visual", "layout_rules", "continuity_locks"))
        lid = data.get("location_id")
        if not isinstance(lid, str) or not re.fullmatch(r"LOC-[A-Z0-9-]+", lid):
            check.error(path, "location_id must match LOC-[A-Z0-9-]+")
            continue
        if lid in locations:
            check.error(path, f"duplicate location_id {lid}")
        locations[lid] = data

    # Every registered asset must resolve to a known character, family, or location.
    known_entities = set(characters) | set(catalog_entries) | set(families) | set(locations)
    for asset_id, entry in asset_entries.items():
        for entity_id in entry.get("entity_ids", []):
            if entity_id not in known_entities:
                check.error(manifest_path, f"{asset_id} references unknown entity {entity_id}")

    if series.get("protagonist_id") not in characters:
        check.error(series_path, "protagonist_id does not resolve to a character card")

    relationships_path = ROOT / "series-bible" / "relationships.json"
    relationships = check.load(relationships_path)
    for relation in relationships.get("relationships", []):
        for cid in relation.get("character_ids", []):
            if cid not in characters:
                check.error(relationships_path, f"relationship references unknown character {cid}")

    episode_ids: dict[str, Path] = {}
    development_root = ROOT / "episodes" / "in-development"
    for episode_path in sorted(development_root.glob("*/episode.json")):
        package = episode_path.parent
        episode = check.load(episode_path)
        check_schema_path(check, episode_path, episode)
        require_keys(check, episode_path, episode, (
            "episode_id", "slug", "title", "status", "premise", "character_want",
            "emotional_need", "lesson", "cast_ids", "location_ids", "scene_ids", "production"
        ))
        eid = episode.get("episode_id")
        if not isinstance(eid, str) or not re.fullmatch(r"EP-\d{3,}", eid):
            check.error(episode_path, "episode_id must look like EP-001")
            continue
        if eid in episode_ids:
            check.error(episode_path, f"duplicate episode_id {eid}")
        episode_ids[eid] = episode_path
        if episode.get("status") not in VALID_STATUSES:
            check.error(episode_path, f"unknown episode status {episode.get('status')!r}")
        if "{{" in episode_path.read_text(encoding="utf-8") or "TODO" in episode_path.read_text(encoding="utf-8"):
            if episode.get("status") not in {"concept"}:
                check.error(episode_path, "unresolved template tokens/TODO values are allowed only at concept status")

        cast = episode.get("cast_ids", [])
        location_ids = episode.get("location_ids", [])
        for cid in cast:
            if cid not in characters:
                check.error(episode_path, f"cast_ids references unknown character {cid}")
        for lid in location_ids:
            if lid not in locations:
                check.error(episode_path, f"location_ids references unknown location {lid}")
        if len(cast) != len(set(cast)):
            check.error(episode_path, "cast_ids contains duplicates")
        if len(location_ids) != len(set(location_ids)):
            check.error(episode_path, "location_ids contains duplicates")

        expected_scenes = episode.get("scene_ids", [])
        scenes: dict[str, dict[str, Any]] = {}
        for scene_path in sorted((package / "scenes").glob("*.json")):
            scene = check.load(scene_path)
            check_schema_path(check, scene_path, scene)
            require_keys(check, scene_path, scene, (
                "episode_id", "scene_id", "sequence", "location_id", "character_ids",
                "visual_action", "continuity_in", "continuity_out"
            ))
            sid = scene.get("scene_id")
            if scene.get("episode_id") != eid:
                check.error(scene_path, f"episode_id must be {eid}")
            if not isinstance(sid, str):
                check.error(scene_path, "scene_id must be a string")
                continue
            if sid in scenes:
                check.error(scene_path, f"duplicate scene_id {sid}")
            scenes[sid] = scene
            if scene.get("location_id") not in location_ids:
                check.error(scene_path, "scene location must be listed in episode.location_ids")
            for cid in scene.get("character_ids", []):
                if cid not in cast:
                    check.error(scene_path, f"scene character {cid} must be listed in episode.cast_ids")
            continuity_text = " ".join(map(str, scene.get("continuity_in", []))).lower()
            if "barefoot" not in continuity_text and "bare paws" not in continuity_text:
                check.error(scene_path, "continuity_in must explicitly preserve barefoot characters or bare paws")

        if set(expected_scenes) != set(scenes):
            missing = sorted(set(expected_scenes) - set(scenes))
            extra = sorted(set(scenes) - set(expected_scenes))
            if missing:
                check.error(episode_path, f"scene_ids missing scene files: {', '.join(missing)}")
            if extra:
                check.error(episode_path, f"scene files not listed in scene_ids: {', '.join(extra)}")
        sequences = [scene.get("sequence") for scene in scenes.values()]
        if len(sequences) != len(set(sequences)):
            check.error(episode_path, "scene sequence values must be unique")

        outline_path = package / "story" / "outline.json"
        if not outline_path.is_file():
            check.error(episode_path, "missing story/outline.json")
        else:
            outline = check.load(outline_path)
            check_schema_path(check, outline_path, outline)
            if outline.get("episode_id") != eid:
                check.error(outline_path, f"episode_id must be {eid}")
            if len(outline.get("escalations", [])) < 3:
                check.error(outline_path, "outline must contain at least three escalations")

        dialogue_path = package / "dialogue" / "dialogue.json"
        dialogue = check.load(dialogue_path) if dialogue_path.is_file() else {}
        if not dialogue:
            check.error(episode_path, "missing dialogue/dialogue.json")
        else:
            check_schema_path(check, dialogue_path, dialogue)
        line_ids: list[str] = []
        for line in dialogue.get("lines", []):
            line_id = line.get("line_id")
            if isinstance(line_id, str):
                line_ids.append(line_id)
            if line.get("scene_id") not in scenes:
                check.error(dialogue_path, f"line {line_id} references unknown scene")
            if line.get("speaker_id") not in cast:
                check.error(dialogue_path, f"line {line_id} speaker must be in episode cast")
        if duplicates(line_ids):
            check.error(dialogue_path, f"duplicate dialogue line IDs: {', '.join(sorted(duplicates(line_ids)))}")

        storyboard_path = package / "storyboards" / "storyboard.json"
        storyboard = check.load(storyboard_path) if storyboard_path.is_file() else {}
        if not storyboard:
            check.error(episode_path, "missing storyboards/storyboard.json")
        else:
            check_schema_path(check, storyboard_path, storyboard)
        shots: dict[str, dict[str, Any]] = {}
        for shot in storyboard.get("shots", []):
            shot_id = shot.get("shot_id")
            if not isinstance(shot_id, str):
                check.error(storyboard_path, "every shot needs a string shot_id")
                continue
            if shot_id in shots:
                check.error(storyboard_path, f"duplicate shot_id {shot_id}")
            shots[shot_id] = shot
            if shot.get("scene_id") not in scenes:
                check.error(storyboard_path, f"shot {shot_id} references unknown scene")
            for line_id in shot.get("dialogue_line_ids", []):
                if line_id not in line_ids:
                    check.error(storyboard_path, f"shot {shot_id} references unknown line {line_id}")

        prompts_path = package / "prompts" / "generation-prompts.json"
        prompts_file = check.load(prompts_path) if prompts_path.is_file() else {}
        if not prompts_file:
            check.error(episode_path, "missing prompts/generation-prompts.json")
        else:
            check_schema_path(check, prompts_path, prompts_file)
        if prompts_file.get("episode_id") not in {None, eid}:
            check.error(prompts_path, f"episode_id must be {eid}")
        prompt_ids: list[str] = []
        for prompt in prompts_file.get("prompts", []):
            pid = prompt.get("prompt_id", "<unknown>")
            prompt_ids.append(str(pid))
            if prompt.get("shot_id") not in shots:
                check.error(prompts_path, f"prompt {pid} references unknown shot {prompt.get('shot_id')}")
            if prompt.get("scene_id") not in scenes:
                check.error(prompts_path, f"prompt {pid} references unknown scene")
            if prompt.get("location_id") not in location_ids:
                check.error(prompts_path, f"prompt {pid} references location outside episode")
            prompt_characters = prompt.get("character_ids", [])
            for cid in prompt_characters:
                if cid not in cast:
                    check.error(prompts_path, f"prompt {pid} references character outside episode cast: {cid}")
            bindings = prompt.get("reference_images", [])
            identity_bindings: dict[str, dict[str, Any]] = {}
            for binding in bindings:
                if not isinstance(binding, dict):
                    check.error(prompts_path, f"prompt {pid} has a non-object reference image binding")
                    continue
                entity_id = binding.get("entity_id")
                if binding.get("purpose") == "identity" and isinstance(entity_id, str):
                    if entity_id in identity_bindings:
                        check.error(prompts_path, f"prompt {pid} has duplicate identity bindings for {entity_id}")
                    identity_bindings[entity_id] = binding
                accepted = set(binding.get("accepted_asset_classes", []))
                if not accepted or not accepted.issubset(IDENTITY_REFERENCE_CLASSES):
                    check.error(prompts_path, f"prompt {pid} reference {entity_id} permits a non-canon asset class")
                if binding.get("manifest_path") != "assets/asset-manifest.json":
                    check.error(prompts_path, f"prompt {pid} reference {entity_id} must resolve through the asset manifest")
                if binding.get("required") and binding.get("missing_reference_behavior") != "block_generation":
                    check.error(prompts_path, f"prompt {pid} required reference {entity_id} must block when missing")
                asset_ids = binding.get("asset_ids", [])
                if binding.get("required") and not asset_ids and episode.get("status") in {"prompt-ready", "production", "completed"}:
                    check.error(prompts_path, f"prompt {pid} required reference {entity_id} has no approved asset IDs")
                for asset_id in asset_ids:
                    entry = asset_entries.get(asset_id)
                    if entry is None:
                        check.error(prompts_path, f"prompt {pid} references unknown manifest asset {asset_id}")
                        continue
                    if entry.get("asset_class") not in accepted:
                        check.error(prompts_path, f"prompt {pid} asset {asset_id} has an unaccepted class")
                    approval = entry.get("approval", {})
                    if approval.get("status") != "approved_for_reference":
                        check.error(prompts_path, f"prompt {pid} asset {asset_id} is not approved_for_reference")
                    if entity_id not in entry.get("entity_ids", []):
                        check.error(prompts_path, f"prompt {pid} asset {asset_id} is not linked to {entity_id}")
            missing_identity_bindings = sorted(set(prompt_characters) - set(identity_bindings))
            if missing_identity_bindings:
                check.error(prompts_path, f"prompt {pid} lacks identity reference bindings for: {', '.join(missing_identity_bindings)}")
            positive = prompt.get("positive_prompt", {})
            barefoot_lock = str(positive.get("barefoot_lock", "")).lower() if isinstance(positive, dict) else ""
            creator_lock = str(positive.get("creator_design_lock", "")).lower() if isinstance(positive, dict) else ""
            if "bare" not in barefoot_lock:
                check.error(prompts_path, f"prompt {pid} needs an explicit positive barefoot_lock")
            if "creator" not in creator_lock or "preserve" not in creator_lock or "do not invent" not in creator_lock:
                check.error(prompts_path, f"prompt {pid} needs a creator_design_lock that preserves official art and blocks invention")
            negative = " ".join(map(str, prompt.get("negative_constraints", []))).lower()
            missing_exclusions = [term for term in BAREFOOT_EXCLUSIONS if term not in negative]
            if missing_exclusions:
                check.error(prompts_path, f"prompt {pid} is missing footwear exclusions: {', '.join(missing_exclusions)}")
            for term in ("redesign", "reinterpret", "ai-generated character identity reference"):
                if term not in negative:
                    check.error(prompts_path, f"prompt {pid} negative constraints must include {term!r}")
        if duplicates(prompt_ids):
            check.error(prompts_path, f"duplicate prompt IDs: {', '.join(sorted(duplicates(prompt_ids)))}")

        audio_path = package / "audio" / "audio-notes.json"
        audio = check.load(audio_path) if audio_path.is_file() else {}
        if not audio:
            check.error(episode_path, "missing audio/audio-notes.json")
        else:
            check_schema_path(check, audio_path, audio)
            for scene_audio in audio.get("scene_audio", []):
                if scene_audio.get("scene_id") not in scenes:
                    check.error(audio_path, f"audio notes reference unknown scene {scene_audio.get('scene_id')}")

        continuity_path = package / "continuity" / "continuity-check.json"
        continuity = check.load(continuity_path) if continuity_path.is_file() else {}
        if not continuity:
            check.error(episode_path, "missing continuity/continuity-check.json")
        else:
            check_schema_path(check, continuity_path, continuity)
            check_ids = {item.get("check_id") for item in continuity.get("checks", [])}
            for required in (
                "CREATOR-VISUAL-AUTHORITY",
                "APPROVED-REFERENCE-IMAGES",
                "BAREFOOT-VISUAL",
                "BAREFOOT-PROMPTS",
                "FAMILY-SAFE",
            ):
                if required not in check_ids:
                    check.error(continuity_path, f"missing required continuity check {required}")
            if episode.get("status") in {"prompt-ready", "production", "completed"} and continuity.get("check_status") != "passed":
                check.error(continuity_path, f"status {episode.get('status')} requires a passed continuity check")

    # Validate completion records and ensure completed episode statuses have one.
    completed_ids: set[str] = set()
    records_root = ROOT / "episodes" / "completed" / "records"
    for record_path in sorted(records_root.glob("*.json")):
        record = check.load(record_path)
        check_schema_path(check, record_path, record)
        eid = record.get("episode_id")
        if eid not in episode_ids:
            check.error(record_path, f"completion record references unknown episode {eid}")
        completed_ids.add(str(eid))
        if record.get("asset_manifest") != "assets/asset-manifest.json":
            check.error(record_path, "completion record must resolve assets through assets/asset-manifest.json")
        if not record.get("final_assets"):
            check.error(record_path, "completion record must contain at least one verified final asset")
        for final_asset in record.get("final_assets", []):
            asset_id = final_asset.get("asset_id")
            entry = asset_entries.get(asset_id)
            if entry is None:
                check.error(record_path, f"final asset {asset_id} is missing from the asset manifest")
            elif entry.get("asset_class") != "final_approved_production_asset":
                check.error(record_path, f"final asset {asset_id} has the wrong asset class")
    for eid, path in episode_ids.items():
        data = check.load(path)
        if data.get("status") == "completed" and eid not in completed_ids:
            check.error(path, "completed status requires a record in episodes/completed/records")

    return check


def main() -> int:
    result = validate()
    for issue in result.warnings:
        print(f"WARNING: {issue.render()}")
    for issue in result.errors:
        print(f"ERROR: {issue.render()}")
    if result.errors:
        print(f"\nValidation failed: {len(result.errors)} error(s), {len(result.warnings)} warning(s).")
        return 1
    character_count = len(list((ROOT / "series-bible" / "characters").glob("*.json")))
    location_count = len(list((ROOT / "series-bible" / "locations").glob("*.json")))
    episode_count = len(list((ROOT / "episodes" / "in-development").glob("*/episode.json")))
    visual_record_count = len(list((ROOT / "assets" / "characters" / "records").glob("*.json")))
    manifest = result.documents.get(ROOT / "assets" / "asset-manifest.json", {})
    asset_count = len(manifest.get("entries", []))
    catalog = result.documents.get(ROOT / "assets" / "characters" / "character-catalog.json", {})
    catalog_count = len(catalog.get("entries", []))
    shell_count = sum(1 for entry in catalog.get("entries", []) if entry.get("catalog_status") == "registered_shell")
    family_count = len(list((ROOT / "assets" / "characters" / "families").glob("*.json")))
    print(
        "Validation passed: "
        f"{character_count} characters, {visual_record_count} visual records, "
        f"{catalog_count} catalog entries ({shell_count} shells), {family_count} families, "
        f"{location_count} locations, {asset_count} registered assets, "
        f"{episode_count} in-development episode(s), {result.json_count} JSON documents."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
