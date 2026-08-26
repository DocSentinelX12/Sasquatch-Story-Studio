APPEND = '''


# ---------------------------------------------------------------------------
# Milestone G: character consistency report (read-only)
# ---------------------------------------------------------------------------

# Fields on Character that carry canon/continuity information. Empty optional
# fields are a WARNING (missing info), never a blocker by themselves.
_CONSISTENCY_FIELDS = (
    ("standard_appearance", "Standard appearance"),
    ("current_outfit", "Current outfit"),
    ("standard_props", "Standard props"),
    ("personality_rules", "Personality rules"),
    ("visual_rules", "Visual rules"),
    ("never_changes", "Never-changes rules"),
)

_BAREFOOT_TERMS = ("shoes", "boots", "socks", "sandals", "slippers", "sneakers", "heels",
                   "footwear", "barefoot")


def character_consistency_report(
    db: Session,
    character_id: int | None = None,
    episode_id: int | None = None,
    scene_id: int | None = None,
) -> dict:
    """Milestone G: read-only character consistency report.

    Compares stored canon/continuity data against actual production data
    (casting, shot references, packages) using only what exists in the
    database. Never creates, queues, approves, or modifies anything.
    """
    from ..models import (CanonEntry, CharacterReference, ContinuityRecord,
                          GenerationResult, Prop, SceneCharacter, ShotCharacter)

    # --- validate filters cleanly -------------------------------------------
    if character_id is not None and db.get(Character, character_id) is None:
        raise ValueError(f"Unknown character id {character_id}")
    if episode_id is not None and db.get(Episode, episode_id) is None:
        raise ValueError(f"Unknown episode id {episode_id}")
    if scene_id is not None and db.get(Scene, scene_id) is None:
        raise ValueError(f"Unknown scene id {scene_id}")

    character_query = select(Character).order_by(Character.project_id, Character.name)
    if character_id is not None:
        character_query = character_query.where(Character.id == character_id)
    characters = db.scalars(character_query).all()

    # scene scope: explicit scene > scenes of an episode > all scenes
    scoped_scene_ids: set[int] | None = None
    if scene_id is not None:
        scoped_scene_ids = {scene_id}
    elif episode_id is not None:
        scoped_scene_ids = set(db.scalars(select(Scene.id).where(
            Scene.episode_id == episode_id)).all())

    findings: list[dict] = []
    affected_scene_ids: set[int] = set()
    affected_shot_ids: set[int] = set()
    missing_references = 0
    missing_rules = 0

    barefoot_canon = db.scalar(select(CanonEntry.statement).where(
        CanonEntry.title == "Barefoot rule"))

    def add(severity, f_type, character, message, reason, route_key, action,
            episode=None, scene=None, shot=None):
        route = LINKS.get(route_key, LINKS["character"])
        if "{id}" in route:
            link_id = shot or scene or episode or character.id
            route = route.format(id=link_id)
        findings.append({
            "severity": severity, "type": f_type,
            "character_id": character.id,
            "episode_id": episode, "scene_id": scene, "shot_id": shot,
            "message": message, "reason": reason,
            "route": route, "action": action,
        })

    for character in characters:
        ep_scope = episode_id

        # 1. lifecycle status -------------------------------------------------
        if character.life_status == "archived":
            scene_links = db.scalars(select(SceneCharacter).where(
                SceneCharacter.character_id == character.id)).all()
            if scene_links:
                add("blocker", "lifecycle", character,
                    f"Archived character {character.name} is still cast in scenes",
                    "Archived characters should not receive new production work",
                    "character", "review casting")
                for link in scene_links:
                    affected_scene_ids.add(link.scene_id)
        elif character.life_status == "draft":
            add("info", "lifecycle", character,
                f"{character.name} is still a draft character",
                "Draft characters can be cast but are not canon-verified",
                "character", "finalize character")

        # 2. approved reference availability ------------------------------------
        approved_refs = db.scalars(select(CharacterReference).where(
            CharacterReference.character_id == character.id,
            CharacterReference.approval_status == "approved")).all()
        if not approved_refs:
            missing_references += 1
            add("warning", "missing_reference", character,
                f"{character.name} has no approved reference images",
                "Generation packages will contain no character reference images; "
                "identity consistency relies on prompts alone",
                "character", "add and approve references")
        else:
            has_primary = any(r.is_primary for r in approved_refs)
            if not has_primary:
                add("info", "reference_primary", character,
                    f"{character.name} has {len(approved_refs)} approved reference(s) but none marked primary",
                    "Reference packages prioritize a primary image when present",
                    "character", "mark a primary reference")

        # 3-8. canon/continuity field availability ---------------------------------
        character_missing_rules = 0
        for field_name, label in _CONSISTENCY_FIELDS:
            value = getattr(character, field_name, None)
            if value in (None, "", [], {}):
                character_missing_rules += 1
                add("warning", "missing_" + field_name, character,
                    f"{character.name} has no {label.lower()} recorded",
                    f"{label} is optional but improves generation consistency",
                    "character", f"fill in {label.lower()}")
        missing_rules += character_missing_rules

        # 9. relationships -----------------------------------------------------------
        relationship_count = len(character.outgoing_relationships or [])
        if relationship_count == 0 and character.character_kind == "person":
            add("info", "relationships", character,
                f"{character.name} has no recorded relationships",
                "Relationships feed the Scene/Shot continuity packages",
                "character", "add relationships")

        # 10. scene casting within scope ------------------------------------------------
        scene_links = db.scalars(select(SceneCharacter).where(
            SceneCharacter.character_id == character.id)).all()
        if scoped_scene_ids is not None:
            scene_links = [l for l in scene_links if l.scene_id in scoped_scene_ids]
        for link in scene_links:
            scene = db.get(Scene, link.scene_id)
            if scene is None:
                continue
            affected_scene_ids.add(scene.id)
            # cast in a scene whose location has no approved reference assets
            if scene.location_id is not None:
                from ..models import Asset, Location
                location = db.get(Location, scene.location_id)
                if location is not None:
                    bg = db.scalar(select(Asset.id).where(
                        Asset.location_id == location.id, Asset.status == "approved"))
                    if bg is None:
                        add("info", "scene_location_reference", character,
                            f"{character.name} appears in a scene whose location "
                            f"'{location.name}' has no approved background reference",
                            "Optional, but location references improve consistency",
                            "scene_director", "add location reference",
                            episode=scene.episode_id, scene=scene.id)

        # 11-12. shot casting + approved references in generation packages -----------------
        shot_links = db.scalars(select(ShotCharacter).where(
            ShotCharacter.character_id == character.id)).all()
        for link in shot_links:
            shot = db.get(Shot, link.shot_id)
            if shot is None:
                continue
            if scoped_scene_ids is not None and shot.scene_id not in scoped_scene_ids:
                continue
            scene = db.get(Scene, shot.scene_id)
            affected_shot_ids.add(shot.id)
            # the actual generation gate check for this shot (reuses validate_shot)
            from .shot_package import validate_shot as _validate
            validation = _validate(db, shot)
            for finding in validation["findings"]:
                if finding["severity"] == "error" and not finding["overridden"] and (
                        finding["key"].startswith("character-") and str(character.id) in finding["key"]):
                    add("blocker", "shot_gate", character,
                        f"Shot {shot.shot_ref or shot.id} blocked: {finding['message']}",
                        finding["key"], "generate", "resolve before generating",
                        episode=scene.episode_id if scene else None,
                        scene=shot.scene_id, shot=shot.id)

        # 13. character-owned props ------------------------------------------------------------
        owned_props = db.scalars(select(Prop).where(
            Prop.owner_character_id == character.id)).all()
        for prop in owned_props:
            if prop.approval_status != "approved":
                add("warning", "prop_approval", character,
                    f"Prop '{prop.name}' owned by {character.name} is not approved",
                    "Unapproved props in packages risk inconsistent depictions",
                    "character", "approve the prop")

        # 14. character-related continuity events --------------------------------------------------
        events = db.scalars(select(ContinuityRecord).where(
            ContinuityRecord.kind.in_(["clothing", "injury", "relationship",
                                       "character_location", "event", "discovery"]))).all()
        char_events = []
        for event in events:
            details = event.details or {}
            if details.get("character_id") == character.id or (
                    isinstance(details.get("characters"), list)
                    and character.id in details.get("characters", [])):
                char_events.append(event)
        for event in char_events:
            if event.status != "canon":
                add("info", "continuity_event", character,
                    f"Draft continuity event for {character.name}: {event.summary[:80]}",
                    "Draft events are not yet canon; approve them when confirmed",
                    "assistant", "review continuity event")

        # 15. barefoot canon vs stored character data ---------------------------------------------------
        if barefoot_canon:
            text_blob = " ".join(filter(None, [
                character.current_outfit, character.clothing,
                character.standard_appearance])).lower()
            for term in _BAREFOOT_TERMS:
                if term in text_blob and term != "barefoot":
                    idx = text_blob.find(term)
                    context = text_blob[max(0, idx - 25):idx + len(term) + 5]
                    if "barefoot" not in context and "no " + term.split()[0] not in context:
                        add("blocker", "barefoot_canon", character,
                            f"Possible footwear mention ('{term}') in {character.name}'s stored outfit/appearance data",
                            "Contradicts the stored barefoot canon rule",
                            "character", "remove the footwear reference")
                        break

    # 16-17. cross-checks are embedded above (production vs canon contradictions
    # appear as blocker findings; missing info as warnings).

    # deduplicate identical findings (same severity+type+character+scene+shot+message)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for finding in findings:
        key = (finding["severity"], finding["type"], finding["character_id"],
               finding["scene_id"], finding["shot_id"], finding["message"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)

    severity_order = {"blocker": 0, "warning": 1, "info": 2}
    deduped.sort(key=lambda f: (severity_order[f["severity"]], f["character_id"] or 0,
                                f["type"], f["scene_id"] or 0, f["shot_id"] or 0))

    blockers = [f for f in deduped if f["severity"] == "blocker"]
    warnings = [f for f in deduped if f["severity"] == "warning"]
    infos = [f for f in deduped if f["severity"] == "info"]

    return {
        "character": (row_to_dict_character(characters[0])
                      if character_id is not None and characters else None),
        "summary": {
            "characters_scanned": len(characters),
            "blockers": len(blockers),
            "warnings": len(warnings),
            "info": len(infos),
            "missing_references": missing_references,
            "missing_rules": missing_rules,
            "affected_scenes": len(affected_scene_ids),
            "affected_shots": len(affected_shot_ids),
            "note": "Read-only report from stored data. No percentages, time "
                    "estimates, or confidence scores — only concrete counts.",
        },
        "findings": deduped,
        "affected_scenes": sorted(affected_scene_ids),
        "affected_shots": sorted(affected_shot_ids),
    }


def row_to_dict_character(character: Character) -> dict:
    return {
        "id": character.id, "char_ref": character.char_ref, "name": character.name,
        "species": character.species, "life_status": character.life_status,
        "approval_status": character.approval_status, "is_canon": character.is_canon,
    }
'''

with open("studio/services/planner.py", "a", encoding="utf-8") as f:
    f.write(APPEND)
print("APPENDED character_consistency_report")
