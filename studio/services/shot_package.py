"""Phase 4 service: shot reference assembly, validation, and generation packages.

This module gathers approved production references, runs rule-based continuity
validation (never auto-fixing), and assembles the provider-neutral generation
package Phase 5 will submit to video providers. No network calls, no simulated
generation results — assembly only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..models import (
    Asset,
    Character,
    CharacterReference,
    ContinuityRecord,
    Episode,
    GenerationPromptPackage,
    Location,
    Prop,
    Scene,
    SceneCharacter,
    SceneProp,
    ScriptElement,
    Shot,
    ShotCharacter,
    ShotContinuity,
    ShotProp,
    ShotReference,
    Storyboard,
    StoryBible,
)

BAREFOOT_RULE = (
    "ALL CHARACTERS ARE ALWAYS BAREFOOT. NO SHOES, SOCKS, BOOTS, SANDALS, "
    "SLIPPERS, OR ANY OTHER FOOTWEAR."
)

FOOTWEAR_TERMS = ("shoes", "boots", "socks", "sandals", "slippers", "sneakers", "heels")
FOOTWEAR_ALLOW = ("no shoes", "without shoes", "barefoot", "not wearing")


# ---------------------------------------------------------------------------
# Reference gathering (PART 5, 6, 7)
# ---------------------------------------------------------------------------

def _approved_character_references(db: Session, character_id: int) -> list[CharacterReference]:
    return db.scalars(
        select(CharacterReference)
        .where(
            CharacterReference.character_id == character_id,
            CharacterReference.approval_status == "approved",
        )
        .options(joinedload(CharacterReference.asset))
        .order_by(CharacterReference.is_primary.desc(), CharacterReference.id)
    ).all()


def character_reference_payload(db: Session, character: Character) -> dict:
    """Approved production reference payload for one character."""
    refs = _approved_character_references(db, character.id)
    by_purpose: dict[str, list] = {}
    for ref in refs:
        if ref.asset is None:
            continue
        entry = {
            "reference_id": f"CHRREF-{ref.id}",
            "asset_id": ref.asset.id,
            "purpose": ref.purpose,
            "label": ref.label or ref.asset.title,
            "path": ref.asset.repo_path,
            "sha256": ref.asset.sha256,
            "asset_class": ref.asset.asset_class,
            "status": ref.asset.status,
        }
        bucket = "primary" if ref.is_primary or ref.purpose in ("primary", "identity") else ref.purpose
        by_purpose.setdefault(bucket, []).append(entry)
    return {
        "character_id": character.char_ref or f"CHAR-{character.id}",
        "name": character.name,
        "species": character.species,
        "standard_appearance": character.standard_appearance or character.appearance_summary,
        "outfit": character.current_outfit or character.clothing,
        "standard_props": character.standard_props or [],
        "personality": character.personality_summary,
        "visual_rules": character.visual_rules or [],
        "never_changes": character.never_changes or [],
        "master_visual_prompt": character.master_visual_prompt,
        "negative_prompt": character.negative_prompt,
        "references": by_purpose,
        "approved_reference_count": len(refs),
    }


def location_reference_payload(db: Session, location: Location | None) -> dict | None:
    if location is None:
        return None
    background_refs = db.scalars(
        select(Asset).where(
            Asset.location_id == location.id,
            Asset.status == "approved",
        )
    ).all()
    return {
        "location_id": location.loc_ref or f"LOC-{location.id}",
        "name": location.name,
        "description": location.description,
        "environment": location.environment,
        "background_references": [
            {"asset_id": a.id, "path": a.repo_path, "sha256": a.sha256, "title": a.title}
            for a in background_refs
        ],
        "visual_rules": location.visual_rules or [],
        "time_of_day_notes": location.time_of_day_notes,
        "weather_notes": location.weather_notes,
        "continuity_notes": location.continuity_notes,
        "approval_status": location.approval_status,
        "approved_reference_count": len(background_refs),
    }


def prop_reference_payload(db: Session, prop: Prop) -> dict:
    owner = db.get(Character, prop.owner_character_id) if prop.owner_character_id else None
    # Reference images for a prop come from shot/asset links; keep honest here.
    return {
        "prop_id": f"PROP-{prop.id}",
        "name": prop.name,
        "description": prop.description,
        "associated_character": owner.name if owner else None,
        "continuity_notes": prop.continuity_notes,
        "approval_status": prop.approval_status,
    }


def scene_script_payload(db: Session, scene: Scene) -> list[dict]:
    elements = db.scalars(
        select(ScriptElement).where(ScriptElement.scene_id == scene.id)
        .order_by(ScriptElement.order_index, ScriptElement.id)
    ).all()
    return [
        {
            "type": e.element_type,
            "speaker": e.character.name if e.character else e.character_name,
            "narrator": e.narrator_name,
            "text": e.text,
            "timing_notes": e.timing_notes,
            "order": e.order_index,
        }
        for e in elements
    ]


# ---------------------------------------------------------------------------
# Validation (PART 9, 14, 20)
# ---------------------------------------------------------------------------

def validate_shot(db: Session, shot: Shot) -> dict:
    """Rule-based validation returning structured findings.

    Errors/warnings are recorded as ShotContinuity rows so overrides persist.
    Nothing is ever auto-fixed.
    """
    scene = db.get(Scene, shot.scene_id)
    cast = db.scalars(select(ShotCharacter).where(
        ShotCharacter.shot_id == shot.id)).all()
    prop_links = db.scalars(select(ShotProp).where(
        ShotProp.shot_id == shot.id)).all()
    overrides = {
        row.check_key: row for row in db.scalars(
            select(ShotContinuity).where(ShotContinuity.shot_id == shot.id))
        .all()
    }

    findings: list[dict] = []

    def add(severity: str, key: str, message: str):
        overridden = overrides.get(key)
        findings.append({
            "severity": severity,
            "key": key,
            "message": message,
            "overridden": bool(overridden and overridden.overridden),
            "override_explanation": overridden.override_explanation if overridden else None,
        })

    # 1. scene approval
    if scene is None:
        add("error", "scene-missing", "Scene no longer exists.")
    elif scene.status not in ("approved", "ready_for_storyboard", "in_production", "complete"):
        add("error", "scene-approval", f"Scene is '{scene.status}' — approve the scene first.")

    # 2. character references (PART 5)
    if not cast:
        add("warning", "cast-empty", "No characters cast in this shot.")
    for link in cast:
        character = link.character
        if character is None:
            continue
        if character.approval_status != "approved":
            add("warning", f"character-approval:{character.id}",
                f"{character.name} is not canon-approved.")
        approved = _approved_character_references(db, character.id)
        if not approved:
            add("warning", f"character-reference:{character.id}",
                f"{character.name} has no approved reference images.")
        else:
            has_primary = any(r.is_primary or r.purpose in ("primary", "identity") for r in approved)
            if not has_primary:
                add("info", f"character-primary-reference:{character.id}",
                    f"{character.name} has approved references but none marked primary.")

    # 3. location reference (PART 6)
    if scene is not None and scene.location_id is None:
        add("warning", "location-missing", "Scene has no location set.")
    elif scene is not None:
        location = db.get(Location, scene.location_id)
        if location is None:
            add("warning", "location-missing", "Scene location no longer exists.")
        elif location.approval_status != "approved":
            add("warning", "location-approval",
                f"Location '{location.name}' is not approved.")
        else:
            bg = db.scalar(select(Asset.id).where(
                Asset.location_id == location.id, Asset.status == "approved"))
            if bg is None:
                add("info", "location-reference",
                    f"Location '{location.name}' has no approved background/reference assets (optional).")

    # 4. props approved (PART 7)
    for link in prop_links:
        prop = link.prop
        if prop is None:
            continue
        if prop.approval_status != "approved":
            add("warning", f"prop-approval:{prop.id}",
                f"Prop '{prop.name}' is not approved.")

    # 5. shot completeness (PART 20)
    if not (shot.description or shot.action or shot.character_action):
        add("error", "shot-description", "Shot has no description or action.")
    if not shot.shot_type:
        add("warning", "shot-type", "No shot type set.")
    if not shot.camera_angle and not shot.camera_movement and not shot.camera_notes:
        add("warning", "camera-direction", "No camera direction (angle/movement/notes).")
    if not shot.duration_seconds or shot.duration_seconds <= 0:
        add("error", "shot-duration", "Duration must be greater than zero.")

    # 6. barefoot canon scan of shot text
    if scene is not None:
        text_blob = " ".join(filter(None, [
            shot.description, shot.action, shot.character_action,
            shot.environment_action, shot.composition, shot.visual_style,
        ])).lower()
        for term in FOOTWEAR_TERMS:
            if term in text_blob:
                idx = text_blob.find(term)
                context = text_blob[max(0, idx - 25):idx + len(term) + 5]
                if not any(a in context for a in FOOTWEAR_ALLOW):
                    add("error", "barefoot-canon",
                        f"Possible footwear mention (\"{term}\") — {BAREFOOT_RULE}")
                    break

    # 7. dialogue/narration present (info only — not every shot needs lines)
    if not (shot.dialogue or shot.narration):
        script_lines = scene_script_payload(db, scene) if scene else []
        if not script_lines:
            add("info", "script-empty", "No dialogue, narration, or scene script lines.")

    blocking = [f for f in findings if f["severity"] == "error" and not f["overridden"]]
    warnings = [f for f in findings if f["severity"] == "warning" and not f["overridden"]]
    return {
        "shot_id": shot.id,
        "findings": findings,
        "blocking_errors": len(blocking),
        "open_warnings": len(warnings),
        "passed": len(blocking) == 0,
        "ready": len(blocking) == 0 and len(warnings) == 0,
    }


def sync_continuity_records(db: Session, shot: Shot, validation: dict) -> None:
    """Persist findings as ShotContinuity rows (preserving overrides)."""
    existing = {
        row.check_key: row for row in db.scalars(
            select(ShotContinuity).where(ShotContinuity.shot_id == shot.id)).all()
    }
    seen_keys = set()
    for finding in validation["findings"]:
        seen_keys.add(finding["key"])
        row = existing.get(finding["key"])
        if row is None:
            db.add(ShotContinuity(
                shot_id=shot.id, check_key=finding["key"],
                severity=finding["severity"], message=finding["message"],
            ))
        else:
            row.severity = finding["severity"]
            row.message = finding["message"]
    # drop records for checks that no longer trigger (unless overridden — keep the audit)
    for key, row in existing.items():
        if key not in seen_keys and not row.overridden:
            db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# Prompt + generation package assembly (PART 8, 19)
# ---------------------------------------------------------------------------

def build_prompt_package(db: Session, shot: Shot) -> dict:
    """Assemble the 19-part provider-neutral generation prompt package."""
    scene = db.get(Scene, shot.scene_id)
    episode = db.get(Episode, scene.episode_id) if scene else None
    location = db.get(Location, scene.location_id) if scene and scene.location_id else None
    cast_payload = []
    for link in db.scalars(select(ShotCharacter).where(
            ShotCharacter.shot_id == shot.id)).all():
        if link.character is not None:
            payload = character_reference_payload(db, link.character)
            payload["role_in_shot"] = link.role_in_shot
            payload["expression_note"] = link.expression_note
            payload["action_note"] = link.action_note
            cast_payload.append(payload)
    props_payload = []
    for link in db.scalars(select(ShotProp).where(
            ShotProp.shot_id == shot.id)).all():
        if link.prop is None:
            continue
        payload = prop_reference_payload(db, link.prop)
        payload["usage_notes"] = link.usage_notes
        payload["state_notes"] = link.state_notes
        props_payload.append(payload)
    script = scene_script_payload(db, scene) if scene else []
    bible = db.scalar(select(StoryBible).where(
        StoryBible.project_id == episode.project_id)) if episode else None
    events = db.scalars(select(ContinuityRecord).where(
        ContinuityRecord.episode_id == episode.id)).all() if episode else []

    reference_ids: list[str] = []
    for character in cast_payload:
        for group in character["references"].values():
            reference_ids.extend(entry["reference_id"] for entry in group)

    negative_constraints = [
        "character redesign, reinterpretation, replacement, or simplified design",
        "changed silhouette, anatomy, fur colors, or proportions",
        "invented accessories or alternate costumes",
        BAREFOOT_RULE.replace("ALL CHARACTERS ARE ALWAYS BAREFOOT.", "any footwear of any kind —"),
    ]
    for character in cast_payload:
        if character["negative_prompt"]:
            negative_constraints.append(f"{character['name']}: {character['negative_prompt']}")

    return {
        "package_version": 1,
        "shot_identity": {
            "shot_id": f"SHOT-{shot.id}",
            "shot_ref": shot.shot_ref,
            "number": shot.number,
            "episode": {"id": episode.id, "number": episode.number, "title": episode.title} if episode else None,
            "scene": {"id": scene.id, "scene_ref": scene.scene_ref, "title": scene.title} if scene else None,
        },
        # 1–19 (PART 8)
        "visual_style": shot.visual_style or ((bible.content or {}).get("tone") if bible else None),
        "characters": cast_payload,
        "character_reference_ids": reference_ids,
        "character_appearance_rules": [
            {"character": c["name"], "standard_appearance": c["standard_appearance"],
             "visual_rules": c["visual_rules"], "never_changes": c["never_changes"]}
            for c in cast_payload
        ],
        "clothing": [
            {"character": c["name"], "outfit": c["outfit"]}
            for c in cast_payload if c["outfit"]
        ],
        "props": props_payload,
        "location": location_reference_payload(db, location),
        "background": None,  # filled from shot references below
        "lighting": shot.lighting or (location.time_of_day_notes if location else None),
        "weather": shot.weather or (scene.weather if scene else None),
        "camera": {
            "shot_type": shot.shot_type, "angle": shot.camera_angle,
            "movement": shot.camera_movement, "notes": shot.camera_notes,
            "lens_framing": shot.lens_framing,
        },
        "composition": {
            "description": shot.composition, "subject_position": shot.subject_position,
        },
        "action": {
            "description": shot.description, "general": shot.action,
            "character_action": shot.character_action,
            "facial_expression": shot.facial_expression,
            "environment_action": shot.environment_action,
        },
        "facial_expressions": [
            {"character": (link.character.name if link.character else None),
             "expression": link.expression_note or shot.facial_expression}
            for link in db.scalars(select(ShotCharacter).where(ShotCharacter.shot_id == shot.id)).all()
        ],
        "environment_movement": shot.environment_action,
        "duration_seconds": shot.duration_seconds,
        "continuity_requirements": {
            "shot_notes": shot.continuity_notes,
            "scene_notes": scene.continuity_notes if scene else None,
            "location_state": shot.location_state_notes,
            "character_state": shot.character_state_notes,
            "prop_state": shot.prop_state_notes,
            "previous_shot": shot.prev_shot_id,
            "next_shot": shot.next_shot_id,
            "episode_events": [
                {"kind": e.kind, "summary": e.summary, "status": e.status} for e in events
            ],
            "barefoot_rule": BAREFOOT_RULE,
        },
        "negative_constraints": negative_constraints,
        "dialogue_timing": {
            "shot_dialogue": shot.dialogue,
            "shot_narration": shot.narration,
            "scene_script": script,
            "timing_notes": "Match speech to action beats; narration carries timing_notes per element.",
        },
        "transition": shot.transition,
        "music": shot.music,
        "sound_effects": shot.sound_effects,
    }


def build_generation_package(db: Session, shot: Shot) -> dict:
    """Everything Phase 5 needs to submit this shot to a video provider."""
    scene = db.get(Scene, shot.scene_id)
    episode = db.get(Episode, scene.episode_id) if scene else None
    validation = validate_shot(db, shot)
    prompt_package = build_prompt_package(db, shot)

    # Frame references (PART 11) — attached assets by purpose
    refs = db.scalars(
        select(ShotReference).where(ShotReference.shot_id == shot.id)
        .options(joinedload(ShotReference.asset))
        .order_by(ShotReference.order_index)
    ).all()
    frame_references: dict[str, list] = {}
    for ref in refs:
        if ref.asset is None:
            continue
        entry = {
            "asset_id": ref.asset.id, "purpose": ref.purpose,
            "path": ref.asset.repo_path, "sha256": ref.asset.sha256,
            "label": ref.label or ref.asset.title, "mime_type": ref.asset.mime_type,
        }
        frame_references.setdefault(ref.purpose, []).append(entry)
    if "background" in frame_references:
        prompt_package["background"] = frame_references["background"]

    previous_shot = db.get(Shot, shot.prev_shot_id) if shot.prev_shot_id else None
    return {
        "generation_package_version": 1,
        "status": shot.status,
        "ready_for_generation": shot.status == "ready_for_generation",
        "validation": validation,
        "shot": {
            "id": shot.id, "shot_ref": shot.shot_ref, "number": shot.number,
            "title": shot.title, "generation_status": shot.generation_status,
        },
        "episode": {"id": episode.id, "number": episode.number} if episode else None,
        "scene": {"id": scene.id, "scene_ref": scene.scene_ref} if scene else None,
        "prompt_package": prompt_package,
        "frame_references": frame_references,
        "previous_shot": (
            {"id": previous_shot.id, "shot_ref": previous_shot.shot_ref,
             "last_frame_available": any(
                 r.purpose == "last_frame"
                 for r in db.scalars(select(ShotReference).where(
                     ShotReference.shot_id == previous_shot.id)).all())}
            if previous_shot else None
        ),
        "provider_notes": (
            "Phase 4 assembly only — no provider call has been made. Phase 5 "
            "adapters translate this package via studio/providers/base.py."
        ),
    }


def snapshot_shot(shot: Shot, version_number: int, label: str | None, status: str = "draft") -> dict:
    """Capture the creative fields of a shot as an immutable version snapshot."""
    fields = [
        "title", "description", "shot_type", "camera_angle", "camera_movement",
        "camera_notes", "lens_framing", "composition", "subject_position",
        "duration_seconds", "action", "character_action", "facial_expression",
        "environment_action", "dialogue", "narration", "sound_effects", "music",
        "transition", "visual_style", "lighting", "weather", "continuity_notes",
        "character_state_notes", "prop_state_notes", "location_state_notes",
        "prev_shot_id", "next_shot_id", "status",
    ]
    return {
        "version_number": version_number,
        "label": label,
        "captured_status": status,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "fields": {field: getattr(shot, field) for field in fields},
    }


def store_prompt_package(db: Session, shot: Shot, source: str = "assembly") -> GenerationPromptPackage:
    package = build_prompt_package(db, shot)
    count = len(db.scalars(select(GenerationPromptPackage.id).where(
        GenerationPromptPackage.shot_id == shot.id)).all())
    row = GenerationPromptPackage(shot_id=shot.id, version=count + 1,
                                  package=package, source=source)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Storyboard drafting (PART 16 "Build Storyboard") — deterministic, not AI
# ---------------------------------------------------------------------------

def build_storyboard_draft(db: Session, scene: Scene, shots_per_beat: int = 2) -> dict:
    """Create a draft storyboard by grouping the scene's script elements into
    draft shots. Deterministic structuring of the approved script — the user
    edits every shot afterwards; nothing is auto-approved."""
    board = db.scalar(select(Storyboard).where(Storyboard.scene_id == scene.id))
    if board is None:
        board = Storyboard(scene_id=scene.id, board_status="in_progress")
        db.add(board)
        db.flush()

    existing = db.scalar(select(Shot.id).where(Shot.scene_id == scene.id))
    if existing:
        return {"created": 0, "board_id": board.id,
                "note": "Scene already has shots — board ensured only."}

    elements = db.scalars(
        select(ScriptElement).where(ScriptElement.scene_id == scene.id)
        .order_by(ScriptElement.order_index, ScriptElement.id)
    ).all()
    if not elements:
        return {"created": 0, "board_id": board.id,
                "note": "Scene has no script lines — add script first or create shots manually."}

    # group elements into beats: a new beat starts at a scene_heading or after N dialogue/action elements
    groups: list[list[ScriptElement]] = []
    current: list[ScriptElement] = []
    for element in elements:
        if element.element_type == "scene_heading" and current:
            groups.append(current)
            current = []
        current.append(element)
        if len([e for e in current if e.element_type in ("dialogue", "action")]) >= max(shots_per_beat, 1):
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    order = 0
    created = 0
    for group in groups:
        order += 1
        dialogue_lines = [
            f"{(e.character.name if e.character else e.character_name or '?').upper()}: {e.text}"
            for e in group if e.element_type == "dialogue"
        ]
        narration = " ".join(e.text for e in group if e.element_type == "narration") or None
        action_text = " ".join(e.text for e in group if e.element_type == "action") or None
        heading = next((e.text for e in group if e.element_type == "scene_heading"), None)
        shot = Shot(
            scene_id=scene.id,
            shot_ref=f"{scene.scene_ref}-SHOT-{order:02d}" if scene.scene_ref else f"SHOT-{order:03d}",
            number=order,
            title=heading or (dialogue_lines[0][:40] if dialogue_lines else (action_text or "Untitled shot")[:40]),
            description=action_text or heading,
            action=action_text,
            dialogue=dialogue_lines or None,
            narration=narration,
            duration_seconds=6.0,
            status="draft",
            order_index=order,
        )
        db.add(shot)
        db.flush()
        # inherit scene casting
        for link in db.scalars(select(SceneCharacter).where(
                SceneCharacter.scene_id == scene.id)).all():
            db.add(ShotCharacter(shot_id=shot.id, character_id=link.character_id,
                                 role_in_shot=link.role_in_scene))
        for link in db.scalars(select(SceneProp).where(
                SceneProp.scene_id == scene.id)).all():
            db.add(ShotProp(shot_id=shot.id, prop_id=link.prop_id,
                            usage_notes=link.usage_notes))
        created += 1
    if created:
        board.board_status = "in_progress"
    db.commit()
    return {"created": created, "board_id": board.id, "note": None}
