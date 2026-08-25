"""First-run seeding: import the existing content repository into the database.

Read-only with respect to canon files — nothing in series-bible/, assets/, or
episodes/ is modified. Every seeded row stores its `source_path` so the app can
always point back to the authoritative JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ApprovalStatus,
    Character,
    CharacterBible,
    CharacterRelationship,
    Episode,
    EpisodeStatus,
    Location,
    Project,
    Provider,
    Scene,
    Season,
    Shot,
    StoryBible,
)
from ..providers.registry import DEFINITIONS


def _relationship_kind(text_value: str) -> str:
    """Map a canon relationship description to a structured kind."""
    value = (text_value or "").lower()
    if any(w in value for w in ("brother", "sister", "mother", "father", "son", "daughter",
                                "parent", "family", "sibling", "husband", "wife")):
        return "family"
    if "best friend" in value or "friend" in value:
        return "friend"
    if "enemy" in value or "rival" in value:
        return "enemy"
    if "companion" in value or "pet" in value:
        return "companion"
    if "neighbor" in value:
        return "neighbor"
    if "teacher" in value or "student" in value or "mentor" in value:
        return "mentor"
    if "recurring" in value:
        return "recurring"
    return "other"


def _load_json(path: str) -> dict | None:
    absolute = settings.repo_root / path
    if not absolute.is_file():
        return None
    try:
        return json.loads(absolute.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def seed_if_empty(session: Session) -> dict:
    if session.scalar(select(Project).limit(1)) is not None:
        return {"seeded": False, "reason": "database already contains projects"}

    report: dict = {"seeded": True, "projects": 0, "characters": 0, "locations": 0,
                    "episodes": 0, "scenes": 0, "shots": 0, "providers": 0}

    # --- Providers (mirror the code registry) ---------------------------------
    for definition in DEFINITIONS.values():
        session.add(
            Provider(
                key=definition.key,
                display_name=definition.display_name,
                kind=definition.kind,
                status="not_configured",
                required_env=list(definition.required_env),
                capabilities=list(definition.capabilities),
                docs_url=definition.docs_url,
                notes=definition.notes,
                adapter_module=definition.adapter_module,
            )
        )
    report["providers"] = len(DEFINITIONS)

    # --- Default project from the series bible --------------------------------
    series = _load_json("series-bible/series.json") or {}
    project = Project(
        name=series.get("title", "Sasquatch Story Studio"),
        slug=_slugify(series.get("title", "sasquatch-story-studio")),
        description="Ongoing family-friendly Sasquatch animated series (2D).",
        series_premise=series.get("logline", ""),
        status="active",
        current_season_number=1,
    )
    session.add(project)
    session.flush()
    report["projects"] = 1

    session.add(
        StoryBible(
            project_id=project.id,
            title="Sasquatch Story Studio — Story Bible",
            source_path="series-bible/series.json",
            content={
                "series": series,
                "bible_markdown": "series-bible/SERIES_BIBLE.md",
                "world_rules": "series-bible/world/world-rules.json",
                "relationships": "series-bible/relationships.json",
                "continuity_log": "series-bible/continuity-log.json",
                "visual_authority": (
                    "Creator-provided character artwork is authoritative. AI must "
                    "preserve the established character designs and must not "
                    "redesign characters."
                ),
                "barefoot_rule": (
                    "ALL CHARACTERS ARE ALWAYS BAREFOOT. NO SHOES, SOCKS, BOOTS, "
                    "SANDALS, SLIPPERS, OR ANY OTHER FOOTWEAR."
                ),
            },
        )
    )

    # --- Characters from the catalog + visual records -------------------------
    catalog = _load_json("assets/characters/character-catalog.json") or {"entries": []}
    for entry in catalog.get("entries", []):
        if entry.get("catalog_status") != "active_record":
            continue
        record_path = entry.get("record_path", "")
        record = _load_json(record_path) or {}
        personality = record.get("personality", {}) or {}
        summary_bits = [
            ", ".join(personality.get("core_traits", [])),
            personality.get("performance_summary", ""),
        ]

        def _ref_note(key: str) -> str | None:
            value = record.get(key)
            if isinstance(value, dict) and value.get("notes"):
                return str(value["notes"])
            if isinstance(value, str):
                return value
            return None

        character = Character(
            project_id=project.id,
            char_ref=entry.get("character_id"),
            name=entry.get("character_name", "Unknown"),
            role=record.get("canon_role"),
            description=record.get("canon_role"),
            species=record.get("species") or entry.get("species"),
            family_ref=record.get("family_id") or entry.get("family_id"),
            character_kind=record.get("character_kind", entry.get("character_kind", "person")),
            age_group=record.get("age_group"),
            approximate_age=record.get("approximate_age"),
            personality_summary=" — ".join(bit for bit in summary_bits if bit) or None,
            appearance_summary=None,
            clothing=_ref_note("clothing_reference"),
            colors=None,
            height_proportions=_ref_note("scale_reference"),
            voice_notes=record.get("voice_notes"),
            master_visual_prompt=record.get("master_generation_prompt"),
            negative_prompt=record.get("negative_prompt"),
            continuity_rules=record.get("continuity_rules"),
            standard_appearance=record.get("visual_authority"),
            current_outfit=_ref_note("clothing_reference"),
            standard_props=None,
            personality_rules=None,
            visual_rules=[record["visual_authority"]] if record.get("visual_authority") else None,
            never_changes=record.get("continuity_rules"),
            life_status="active",
            approval_status=ApprovalStatus.APPROVED.value,  # creator canon
            is_canon=True,
            source_path=record_path or None,
        )
        session.add(character)
        session.flush()
        session.add(CharacterBible(
            character_id=character.id,
            source_path=record_path,
            content=record or None,
        ))

        # Import relationships from the canon record (directed, with notes).
        for rel in record.get("relationships", []) or []:
            if not rel.get("character_id"):
                continue
            target = session.scalar(
                select(Character).where(
                    Character.project_id == project.id,
                    Character.char_ref == rel["character_id"],
                )
            )
            if target is None:
                continue
            session.add(CharacterRelationship(
                character_id=character.id,
                related_character_id=target.id,
                kind=_relationship_kind(rel.get("relationship", "")),
                notes=rel.get("relationship"),
            ))
        report["characters"] += 1

    # --- Locations -------------------------------------------------------------
    locations_dir = settings.repo_root / "series-bible" / "locations"
    loc_ref_by_name: dict[str, int] = {}
    if locations_dir.is_dir():
        for file in sorted(locations_dir.glob("*.json")):
            data = _load_json(f"series-bible/locations/{file.name}") or {}
            location = Location(
                project_id=project.id,
                loc_ref=data.get("location_id"),
                name=data.get("name", file.stem.replace("-", " ").title()),
                kind=data.get("kind"),
                description=data.get("description") or data.get("summary"),
                source_path=f"series-bible/locations/{file.name}",
            )
            session.add(location)
            session.flush()
            if data.get("location_id"):
                loc_ref_by_name[data["location_id"]] = location.id
            report["locations"] += 1

    # --- Season 1 + EP-001 (from episodes/in-development) ----------------------
    season = Season(project_id=project.id, number=1, title="Season 1", status="active")
    session.add(season)
    session.flush()

    ep_dir = "episodes/in-development/EP-001-the-great-moonberry-bounce"
    episode_json = _load_json(f"{ep_dir}/episode.json")
    if episode_json is not None:
        episode = Episode(
            project_id=project.id,
            season_id=season.id,
            number=1,
            title=episode_json.get("title", "Episode 1"),
            slug=episode_json.get("slug"),
            status="development",
            logline=episode_json.get("hook_summary"),
            premise=episode_json.get("premise"),
            target_length_minutes=float(episode_json.get("target_length_minutes", 8)),
            source_path=f"{ep_dir}/episode.json",
        )
        session.add(episode)
        session.flush()
        report["episodes"] = 1

        scene_files = sorted((settings.repo_root / ep_dir / "scenes").glob("SC-*.json"))
        for index, scene_file in enumerate(scene_files, start=1):
            data = _load_json(f"{ep_dir}/scenes/{scene_file.name}") or {}
            scene = Scene(
                episode_id=episode.id,
                number=data.get("sequence", index),
                scene_ref=data.get("scene_id"),
                title=data.get("title"),
                slug=_slugify(data.get("title", scene_file.stem)),
                location_id=loc_ref_by_name.get(data.get("location_id")),
                time_of_day=data.get("time"),
                story_purpose=data.get("purpose"),
                visual_action=data.get("visual_action"),
                estimated_duration_seconds=data.get("estimated_duration_seconds"),
                status="needs_review",
                order_index=index,
                source_path=f"{ep_dir}/scenes/{scene_file.name}",
            )
            session.add(scene)
            session.flush()
            report["scenes"] += 1

        storyboard = _load_json(f"{ep_dir}/storyboards/storyboard.json") or {}
        scenes_by_ref = {
            s.scene_ref: s for s in session.scalars(
                select(Scene).where(Scene.episode_id == episode.id)
            ).all() if s.scene_ref
        }
        for index, shot_data in enumerate(storyboard.get("shots", []), start=1):
            scene = scenes_by_ref.get(shot_data.get("scene_id"))
            if scene is None:
                continue
            session.add(Shot(
                scene_id=scene.id,
                shot_ref=shot_data.get("shot_id"),
                number=shot_data.get("sequence", index),
                shot_type=shot_data.get("framing"),
                camera_movement=shot_data.get("camera"),
                duration_seconds=float(shot_data.get("duration_seconds", 6)),
                action=shot_data.get("action"),
                visual_style=shot_data.get("composition"),
                status="draft",
                order_index=index,
                source_path=f"{ep_dir}/storyboards/storyboard.json",
            ))
            report["shots"] += 1

    session.commit()
    return report


def backfill_canon_fields(session: Session) -> int:
    """Idempotent Phase 2 backfill for databases seeded in Phase 1.

    Only fills NULL/missing values; never overwrites user edits.
    """
    updated = 0
    characters = session.scalars(select(Character)).all()
    by_ref = {c.char_ref: c for c in characters if c.char_ref}
    for character in characters:
        changed = False
        if character.life_status in (None, "", "draft") and character.is_canon:
            character.life_status = "active"
            changed = True
        record = None
        if character.source_path and character.bible is None:
            record = _load_json(character.source_path) or {}
            session.add(CharacterBible(
                character_id=character.id,
                source_path=character.source_path,
                content=record or None,
            ))
            changed = True
        record = record or ((character.bible and character.bible.content) or {})
        if record:
            if not character.description:
                character.description = record.get("canon_role")
                changed = changed or character.description is not None
            if not character.standard_appearance and record.get("visual_authority"):
                character.standard_appearance = record["visual_authority"]
                changed = True
            if not character.visual_rules and record.get("visual_authority"):
                character.visual_rules = [record["visual_authority"]]
                changed = True
            if not character.never_changes and record.get("continuity_rules"):
                character.never_changes = record["continuity_rules"]
                changed = True
            existing_out = {
                (r.related_character_id, r.kind)
                for r in (character.outgoing_relationships or [])
            }
            for rel in record.get("relationships", []) or []:
                if not rel.get("character_id"):
                    continue
                target = by_ref.get(rel["character_id"])
                if target is None or target.id == character.id:
                    continue
                kind = _relationship_kind(rel.get("relationship", ""))
                if (target.id, kind) in existing_out:
                    continue
                session.add(CharacterRelationship(
                    character_id=character.id,
                    related_character_id=target.id,
                    kind=kind,
                    notes=rel.get("relationship"),
                ))
                changed = True
        if changed:
            updated += 1
    session.commit()
    return updated


def seed_story_layer(session: Session) -> dict:
    """Idempotent Phase 3 seed/backfill: story bible fields, canon entries,
    EP-001 scene casting + script elements. Never overwrites user edits."""
    from ..models import CanonEntry, Scene, SceneCharacter, ScriptElement

    report = {"bibles": 0, "canon": 0, "cast_links": 0, "script_elements": 0}
    project = session.scalar(select(Project))
    if project is None:
        return report

    # --- Story Bible: enrich structured content + approve creator canon -----
    bible = session.scalar(select(StoryBible).where(StoryBible.project_id == project.id))
    series = _load_json("series-bible/series.json") or {}
    world_rules = _load_json("series-bible/world/world-rules.json") or {}
    style = _load_json("series-bible/world/visual-style.json") or {}
    if bible is not None:
        content = dict(bible.content or {})
        if not content.get("structured"):
            content.update({
                "structured": True,
                "series_title": series.get("title", project.name),
                "premise": series.get("logline", ""),
                "genre": "Family animated comedy adventure",
                "audience": (series.get("format", {}) or {}).get("audience"),
                "tone": series.get("tone", []),
                "setting": "Mossy Hollow — a hidden forest town",
                "world_description": world_rules.get("name"),
                "visual_storytelling_rules": style.get("rules", style.get("principles", [])),
                "humor_rules": [j.get("joke", j) if isinstance(j, dict) else j
                                for j in (_load_json("series-bible/world/running-jokes.json") or {}).get("gags", [])],
                "storytelling_rules": series.get("episode_structure", []),
                "world_rules": [r.get("rule") for r in world_rules.get("rules", []) if isinstance(r, dict)],
                "never_happen": [r for r in world_rules.get("safety_boundaries", []) if isinstance(r, str)],
                "recurring_themes": series.get("recurring_themes", []),
            })
            bible.content = content
            bible.version = (bible.version or 1) + 1
        if not bible.status or bible.status == "draft":
            bible.status = "approved"   # creator-supplied canon starts approved
        report["bibles"] += 1

    # --- Canon entries from world rules + series non-negotiables ------------
    existing_titles = {
        row for row in session.scalars(select(CanonEntry.title).where(CanonEntry.project_id == project.id))
    }

    def add_canon(category: str, title: str, statement: str, details=None, origin="seeded", source_path=None):
        if title in existing_titles:
            return
        session.add(CanonEntry(
            project_id=project.id, category=category, title=title,
            statement=statement, details=details, status="canon",
            origin=origin, source_path=source_path,
        ))
        existing_titles.add(title)
        report["canon"] += 1

    for rule in world_rules.get("rules", []):
        if isinstance(rule, dict):
            add_canon("world", rule.get("rule_id", rule.get("rule", "")[:40]), rule.get("rule", ""),
                      details={"story_effect": rule.get("story_effect")},
                      source_path="series-bible/world/world-rules.json")
    for rule in world_rules.get("safety_boundaries", []):
        if isinstance(rule, str):
            slug = rule[:60]
            add_canon("world", f"NEVER: {slug}", rule, source_path="series-bible/world/world-rules.json")
    for item in series.get("non_negotiables", []):
        if isinstance(item, dict):
            add_canon("episode", f"RULE: {item.get('rule', '')[:60]}", item.get("rule", ""),
                      details={"why": item.get("why")}, source_path="series-bible/series.json")
    add_canon("world", "Barefoot rule",
              "ALL CHARACTERS ARE ALWAYS BAREFOOT. NO SHOES, SOCKS, BOOTS, SANDALS, SLIPPERS, OR ANY OTHER FOOTWEAR.",
              source_path="assets/asset-manifest.json")

    # --- EP-001: scene casting + script elements -----------------------------
    ep_dir = "episodes/in-development/EP-001-the-great-moonberry-bounce"
    episode = session.scalar(select(Episode).where(Episode.project_id == project.id, Episode.number == 1))
    if episode is None:
        session.commit()
        return report

    characters_by_ref = {
        c.char_ref: c for c in session.scalars(
            select(Character).where(Character.project_id == project.id)
        ).all() if c.char_ref
    }
    scenes = session.scalars(select(Scene).where(Scene.episode_id == episode.id)).all()
    scenes_by_ref = {s.scene_ref: s for s in scenes if s.scene_ref}
    for scene in scenes:
        data = _load_json(scene.source_path) if scene.source_path else None
        if not data:
            continue
        for ref in data.get("character_ids", []):
            character = characters_by_ref.get(ref)
            if character is None:
                continue
            exists = session.scalar(
                select(SceneCharacter).where(
                    SceneCharacter.scene_id == scene.id,
                    SceneCharacter.character_id == character.id,
                )
            )
            if exists is None:
                session.add(SceneCharacter(scene_id=scene.id, character_id=character.id))
                report["cast_links"] += 1

    dialogue = _load_json(f"{ep_dir}/dialogue/dialogue.json") or {}
    existing_refs = set(session.scalars(select(ScriptElement.source_ref)).all())
    next_order = 0.0
    for line in dialogue.get("lines", []):
        if line.get("line_id") in existing_refs:
            continue
        scene = scenes_by_ref.get(line.get("scene_id"))
        if scene is None:
            continue
        character = characters_by_ref.get(line.get("speaker_id"))
        next_order += 1
        session.add(ScriptElement(
            scene_id=scene.id,
            episode_id=episode.id,
            order_index=next_order,
            element_type="dialogue",
            character_id=character.id if character else None,
            character_name=None if character else line.get("speaker_id"),
            text=line.get("text", ""),
            timing_notes=line.get("performance_note"),
            notes=line.get("intent"),
            source_ref=line.get("line_id"),
        ))
        if line.get("over_action"):
            next_order += 1
            session.add(ScriptElement(
                scene_id=scene.id,
                episode_id=episode.id,
                order_index=next_order,
                element_type="action",
                text=line.get("over_action"),
                source_ref=f"{line.get('line_id')}-action",
            ))
        report["script_elements"] += 1

    session.commit()
    return report


def refresh_provider_status(session: Session) -> int:
    """Recompute provider status from the server environment into DB rows."""
    from ..providers.registry import DEFINITIONS as REGISTRY

    updated = 0
    rows = {row.key: row for row in session.scalars(select(Provider)).all()}
    for key, definition in REGISTRY.items():
        row = rows.get(key)
        if row is None:
            row = Provider(key=key, display_name=definition.display_name,
                           kind=definition.kind, adapter_module=definition.adapter_module)
            session.add(row)
        row.status = definition.status()
        row.required_env = list(definition.required_env)
        row.capabilities = list(definition.capabilities)
        row.docs_url = definition.docs_url
        row.notes = definition.notes
        updated += 1
    session.commit()
    return updated
