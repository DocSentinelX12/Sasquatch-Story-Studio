"""Phase 4 API: storyboards, shots, casting, references, versions,
validation, approval, and generation packages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..models import (
    Approval,
    Asset,
    Character,
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
    ShotVersion,
    Storyboard,
)
from ..models.shots import (
    CAMERA_ANGLES,
    CAMERA_MOVEMENTS,
    SHOT_REFERENCE_PURPOSES,
    SHOT_STATUSES,
    SHOT_TYPES,
)
from ..services.version_control import (
    VersionControlError,
    compare_versions,
    select_current_version,
    version_detail,
    version_history,
    version_safety_check,
)
from ..services.shot_package import (
    build_generation_package,
    build_prompt_package,
    build_storyboard_draft,
    snapshot_shot,
    store_prompt_package,
    sync_continuity_records,
    validate_shot,
)
from .deps import get_db, row_to_dict

router = APIRouter(prefix="/api", tags=["shots"])

SHOT_ALIASES = {"planned": "draft", "ready": "needs_review", "queued": "generating"}


def _get_shot_or_404(db: Session, shot_id: int) -> Shot:
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(404, "Shot not found")
    return shot


def shot_payload(db: Session, shot: Shot, include_script: bool = False) -> dict:
    cast = db.scalars(
        select(ShotCharacter).where(ShotCharacter.shot_id == shot.id)
        .options(joinedload(ShotCharacter.character))
    ).all()
    prop_links = db.scalars(
        select(ShotProp).where(ShotProp.shot_id == shot.id)
        .options(joinedload(ShotProp.prop))
    ).all()
    refs = db.scalars(
        select(ShotReference).where(ShotReference.shot_id == shot.id)
        .options(joinedload(ShotReference.asset))
        .order_by(ShotReference.order_index)
    ).all()
    storyboard_image = next((r for r in refs if r.purpose == "storyboard_image"), None)
    scene = db.get(Scene, shot.scene_id)
    data = {
        **row_to_dict(shot),
        "scene_ref": scene.scene_ref if scene else None,
        "scene_status": scene.status if scene else None,
        "cast": [
            {**row_to_dict(link), "character": {
                "id": link.character.id, "name": link.character.name,
                "char_ref": link.character.char_ref,
                "approval_status": link.character.approval_status,
            } if link.character else None}
            for link in cast
        ],
        "props": [
            {**row_to_dict(link), "prop": {
                "id": link.prop.id, "name": link.prop.name,
                "approval_status": link.prop.approval_status,
            } if link.prop else None}
            for link in prop_links
        ],
        "references": [
            {**row_to_dict(ref), "asset": {
                "id": ref.asset.id, "title": ref.asset.title,
                "repo_path": ref.asset.repo_path, "mime_type": ref.asset.mime_type,
                "status": ref.asset.status,
            } if ref.asset else None}
            for ref in refs
        ],
        "storyboard_image_url": (
            f"/api/assets/{storyboard_image.asset_id}/file" if storyboard_image else None
        ),
        "version_count": db.scalar(select(func.count(ShotVersion.id)).where(
            ShotVersion.shot_id == shot.id)) or 0,
    }
    return data


# ==========================================================================
# Storyboards + Scene Director payload (PART 1, 16)
# ==========================================================================

@router.post("/scenes/{scene_id}/storyboard", status_code=201)
def ensure_storyboard(scene_id: int, db: Session = Depends(get_db)):
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    board = db.scalar(select(Storyboard).where(Storyboard.scene_id == scene_id))
    if board is None:
        board = Storyboard(scene_id=scene_id, board_status="draft")
        db.add(board)
        db.commit()
        db.refresh(board)
    return row_to_dict(board)


@router.post("/scenes/{scene_id}/storyboard/build")
def build_board(scene_id: int, db: Session = Depends(get_db)):
    """Deterministic draft-shot creation from the scene script (not AI).
    Existing shots are never overwritten."""
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    result = build_storyboard_draft(db, scene)
    return result


@router.get("/scenes/{scene_id}/director")
def scene_director(scene_id: int, db: Session = Depends(get_db)):
    """Scene Director payload: scene info, cast, props, script, continuity,
    storyboard shots, validation summary, production readiness."""
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    board = db.scalar(select(Storyboard).where(Storyboard.scene_id == scene_id))
    shots = db.scalars(
        select(Shot).where(Shot.scene_id == scene_id).order_by(Shot.order_index, Shot.id)
    ).all()
    shot_rows = []
    warnings_total = errors_total = 0
    for shot in shots:
        validation = validate_shot(db, shot)
        errors_total += validation["blocking_errors"]
        warnings_total += validation["open_warnings"]
        shot_rows.append({**shot_payload(db, shot), "validation": {
            "passed": validation["passed"], "ready": validation["ready"],
            "blocking_errors": validation["blocking_errors"],
            "open_warnings": validation["open_warnings"],
        }})
    cast = db.scalars(
        select(SceneCharacter).where(SceneCharacter.scene_id == scene_id)
        .options(joinedload(SceneCharacter.character))
    ).all()
    prop_links = db.scalars(
        select(SceneProp).where(SceneProp.scene_id == scene_id)
        .options(joinedload(SceneProp.prop))
    ).all()
    script = db.scalars(
        select(ScriptElement).where(ScriptElement.scene_id == scene_id)
        .order_by(ScriptElement.order_index)
    ).all()
    location = db.get(Location, scene.location_id) if scene.location_id else None
    readiness = "blocked"
    if scene.status == "ready_for_storyboard" and shots:
        if errors_total == 0 and all(s["status"] in ("ready_for_generation", "complete") for s in shot_rows):
            readiness = "generation_ready"
        elif errors_total == 0:
            readiness = "in_progress"
        else:
            readiness = "needs_work"
    return {
        "scene": row_to_dict(scene),
        "location": row_to_dict(location) if location else None,
        "cast": [
            {"id": link.id, "character": {
                "id": link.character.id, "name": link.character.name,
                "char_ref": link.character.char_ref, "species": link.character.species,
                "approval_status": link.character.approval_status,
                "never_changes": link.character.never_changes,
                "visual_rules": link.character.visual_rules,
            } if link.character else None, "role_in_scene": link.role_in_scene}
            for link in cast
        ],
        "scene_props": [
            {"id": link.id, "prop": {
                "id": link.prop.id, "name": link.prop.name,
                "approval_status": link.prop.approval_status,
                "continuity_notes": link.prop.continuity_notes,
            } if link.prop else None}
            for link in prop_links
        ],
        "script": [row_to_dict(e) for e in script],
        "storyboard": row_to_dict(board) if board else None,
        "shots": shot_rows,
        "summary": {
            "shot_count": len(shot_rows),
            "estimated_duration": sum(s.duration_seconds or 0 for s in shots),
            "blocking_errors": errors_total,
            "open_warnings": warnings_total,
            "ready_for_generation": sum(1 for s in shot_rows if s["status"] == "ready_for_generation"),
            "readiness": readiness,
        },
    }


# ==========================================================================
# Episode storyboard overview (PART 17)
# ==========================================================================

@router.get("/episodes/{episode_id}/board")
def episode_board(episode_id: int, db: Session = Depends(get_db)):
    from ..models import Act

    scenes = db.scalars(
        select(Scene).where(Scene.episode_id == episode_id)
        .options(joinedload(Scene.location))
        .order_by(Scene.order_index)
    ).all()
    acts = db.scalars(select(Act).where(Act.episode_id == episode_id).order_by(Act.number)).all()
    blocks = []
    total_shots = total_duration = ready_count = unapproved = 0
    missing_refs: list[str] = []
    for act in acts:
        act_scenes = [s for s in scenes if s.act_id == act.id]
        blocks.append({"kind": "act", "act": row_to_dict(act),
                       "scene_ids": [s.id for s in act_scenes]})
    grouped: list[dict] = []
    for scene in scenes:
        shots = db.scalars(
            select(Shot).where(Shot.scene_id == scene.id).order_by(Shot.order_index)
        ).all()
        scene_missing = []
        for shot in shots:
            validation = validate_shot(db, shot)
            for finding in validation["findings"]:
                if finding["severity"] == "warning" and "reference" in finding["key"] and not finding["overridden"]:
                    scene_missing.append(f"{shot.shot_ref or shot.id}: {finding['message']}")
        total_shots += len(shots)
        total_duration += sum(s.duration_seconds or 0 for s in shots)
        ready_count += sum(1 for s in shots if s.status == "ready_for_generation")
        unapproved += sum(1 for s in shots if s.status in ("draft", "needs_review"))
        missing_refs.extend(scene_missing[:3])
        grouped.append({
            "kind": "scene",
            "scene": {
                "id": scene.id, "scene_ref": scene.scene_ref, "title": scene.title,
                "status": scene.status, "time_of_day": scene.time_of_day,
                "location_name": scene.location.name if scene.location else None,
                "act_id": scene.act_id,
            },
            "shots": [
                {"id": s.id, "shot_ref": s.shot_ref, "number": s.number,
                 "title": s.title, "status": s.status, "shot_type": s.shot_type,
                 "duration_seconds": s.duration_seconds,
                 "generation_status": s.generation_status}
                for s in shots
            ],
        })
    return {
        "blocks": blocks,
        "scenes": grouped,
        "summary": {
            "scene_count": len(scenes),
            "shot_count": total_shots,
            "estimated_duration_seconds": total_duration,
            "ready_for_generation": ready_count,
            "unapproved_shots": unapproved,
            "missing_references": missing_refs,
        },
    }


# ==========================================================================
# Shots CRUD (PART 2, 3, 4)
# ==========================================================================

class ShotCreate(BaseModel):
    scene_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    shot_type: Optional[str] = None
    camera_angle: Optional[str] = None
    camera_movement: Optional[str] = None
    camera_notes: Optional[str] = None
    duration_seconds: float = 6.0
    action: Optional[str] = None
    dialogue: Optional[list] = None
    narration: Optional[str] = None
    prev_shot_id: Optional[int] = None


class ShotUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    shot_type: Optional[str] = None
    camera_angle: Optional[str] = None
    camera_movement: Optional[str] = None
    camera_notes: Optional[str] = None
    lens_framing: Optional[str] = None
    composition: Optional[str] = None
    subject_position: Optional[str] = None
    duration_seconds: Optional[float] = None
    action: Optional[str] = None
    character_action: Optional[str] = None
    facial_expression: Optional[str] = None
    environment_action: Optional[str] = None
    dialogue: Optional[list] = None
    narration: Optional[str] = None
    sound_effects: Optional[list] = None
    music: Optional[str] = None
    transition: Optional[str] = None
    visual_style: Optional[str] = None
    lighting: Optional[str] = None
    weather: Optional[str] = None
    continuity_notes: Optional[str] = None
    character_state_notes: Optional[str] = None
    prop_state_notes: Optional[str] = None
    location_state_notes: Optional[str] = None
    prev_shot_id: Optional[int] = None
    next_shot_id: Optional[int] = None
    status: Optional[str] = None


@router.post("/shots", status_code=201)
def create_shot(payload: ShotCreate, db: Session = Depends(get_db)):
    scene = db.get(Scene, payload.scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    if payload.shot_type is not None and payload.shot_type not in SHOT_TYPES:
        raise HTTPException(422, f"shot_type must be one of {sorted(SHOT_TYPES)} (or 'custom' + notes)")
    if payload.camera_angle is not None and payload.camera_angle not in CAMERA_ANGLES:
        raise HTTPException(422, f"camera_angle must be one of {sorted(CAMERA_ANGLES)}")
    if payload.camera_movement is not None and payload.camera_movement not in CAMERA_MOVEMENTS:
        raise HTTPException(422, f"camera_movement must be one of {sorted(CAMERA_MOVEMENTS)}")
    count = db.scalar(select(func.count(Shot.id)).where(Shot.scene_id == payload.scene_id)) or 0
    order = (db.scalar(select(func.max(Shot.order_index)).where(
        Shot.scene_id == payload.scene_id)) or 0) + 1
    shot = Shot(
        scene_id=payload.scene_id,
        shot_ref=f"{scene.scene_ref}-SHOT-{count + 1:02d}" if scene.scene_ref else f"SHOT-{count + 1:03d}",
        number=count + 1,
        title=payload.title, description=payload.description,
        shot_type=payload.shot_type, camera_angle=payload.camera_angle,
        camera_movement=payload.camera_movement, camera_notes=payload.camera_notes,
        duration_seconds=payload.duration_seconds, action=payload.action,
        dialogue=payload.dialogue, narration=payload.narration,
        prev_shot_id=payload.prev_shot_id,
        status="draft", order_index=order,
    )
    db.add(shot)
    db.flush()
    # inherit scene casting/props by default
    for link in db.scalars(select(SceneCharacter).where(
            SceneCharacter.scene_id == payload.scene_id)).all():
        db.add(ShotCharacter(shot_id=shot.id, character_id=link.character_id,
                             role_in_shot=link.role_in_scene))
    for link in db.scalars(select(SceneProp).where(
            SceneProp.scene_id == payload.scene_id)).all():
        db.add(ShotProp(shot_id=shot.id, prop_id=link.prop_id, usage_notes=link.usage_notes))
    db.commit()
    db.refresh(shot)
    return shot_payload(db, shot)


@router.get("/shots")
def list_shots(
    scene_id: Optional[int] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    episode_id: Optional[int] = None,
    limit: int = 60,
    after_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    from ..models import Scene as SceneModel
    normalized = SHOT_ALIASES.get(status, status) if status else None
    if normalized is not None and normalized not in SHOT_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(SHOT_STATUSES)}")
    query = select(Shot)
    if scene_id:
        query = query.where(Shot.scene_id == scene_id)
    if episode_id:
        query = query.where(Shot.scene_id.in_(
            select(SceneModel.id).where(SceneModel.episode_id == episode_id)))
    if normalized:
        query = query.where(Shot.status == normalized)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(func.lower(Shot.title).like(like) | func.lower(Shot.description).like(like) |
                            func.lower(Shot.action).like(like))
    if after_id is not None:
        query = query.where(Shot.id > after_id)
        shots = db.scalars(query.order_by(Shot.id).limit(min(limit, 200))).all()
        return {"shots": [shot_payload(db, s) for s in shots],
                "next_cursor": shots[-1].id if len(shots) == min(limit, 200) else None}
    shots = db.scalars(query.order_by(Shot.scene_id, Shot.order_index).limit(min(limit, 200))).all()
    counts = dict(db.execute(select(Shot.status, func.count(Shot.id)).group_by(Shot.status)).all())
    return {"shots": [shot_payload(db, s) for s in shots], "counts_by_status": counts}


@router.get("/shots/{shot_id}")
def get_shot(shot_id: int, db: Session = Depends(get_db)):
    shot = _get_shot_or_404(db, shot_id)
    return {**shot_payload(db, shot), "validation": validate_shot(db, shot)}


@router.patch("/shots/{shot_id}")
def update_shot(shot_id: int, payload: ShotUpdate, db: Session = Depends(get_db)):
    shot = _get_shot_or_404(db, shot_id)
    data = payload.model_dump(exclude_none=True)
    if "status" in data:
        status = SHOT_ALIASES.get(data["status"], data["status"])
        if status not in SHOT_STATUSES:
            raise HTTPException(422, f"status must be one of {sorted(SHOT_STATUSES)}")
        if status in ("ready_for_generation", "approved"):
            raise HTTPException(
                409, "Use POST /shots/{id}/approve and /shots/{id}/ready-for-generation "
                     "to reach approved/ready states.")
        data["status"] = status
    for field in ("shot_type",):
        if field in data and data[field] not in SHOT_TYPES:
            raise HTTPException(422, f"{field} must be one of {sorted(SHOT_TYPES)}")
    for field, allowed in (("camera_angle", CAMERA_ANGLES), ("camera_movement", CAMERA_MOVEMENTS)):
        if field in data and data[field] not in allowed:
            raise HTTPException(422, f"{field} must be one of {sorted(allowed)}")
    for field, value in data.items():
        setattr(shot, field, value)
    db.commit()
    db.refresh(shot)
    return shot_payload(db, shot)


@router.delete("/shots/{shot_id}", status_code=204)
def delete_shot(shot_id: int, db: Session = Depends(get_db)):
    shot = _get_shot_or_404(db, shot_id)
    if shot.status in ("ready_for_generation", "generating", "generated", "complete"):
        raise HTTPException(409, f"Shot in status '{shot.status}' cannot be deleted")
    db.delete(shot)
    db.commit()
    return None


class ShotReorder(BaseModel):
    shot_ids: list[int] = Field(min_length=1)


@router.post("/scenes/{scene_id}/shots/reorder")
def reorder_shots(scene_id: int, payload: ShotReorder, db: Session = Depends(get_db)):
    shots = db.scalars(select(Shot).where(Shot.scene_id == scene_id)).all()
    by_id = {s.id: s for s in shots}
    unknown = [sid for sid in payload.shot_ids if sid not in by_id]
    if unknown:
        raise HTTPException(422, f"Shot ids not in this scene: {unknown}")
    order_map = {sid: idx + 1 for idx, sid in enumerate(payload.shot_ids)}
    for shot in shots:
        shot.order_index = order_map.get(shot.id, shot.order_index)
    ordered = sorted(shots, key=lambda s: s.order_index)
    for idx, shot in enumerate(ordered, start=1):
        shot.number = idx
        scene = db.get(Scene, scene_id)
        prefix = scene.scene_ref if scene and scene.scene_ref else "SHOT"
        shot.shot_ref = f"{prefix}-SHOT-{idx:02d}" if scene and scene.scene_ref else f"SHOT-{idx:03d}"
        # maintain prev/next links automatically
        shot.prev_shot_id = ordered[idx - 2].id if idx >= 2 else None
        shot.next_shot_id = ordered[idx].id if idx < len(ordered) else None
    db.commit()
    return {"shots": [shot_payload(db, s) for s in ordered]}


# ==========================================================================
# Shot casting + props (PART 5, 7)
# ==========================================================================

class ShotCastAdd(BaseModel):
    character_id: int
    role_in_shot: Optional[str] = None
    expression_note: Optional[str] = None
    action_note: Optional[str] = None


@router.post("/shots/{shot_id}/cast", status_code=201)
def add_shot_cast(shot_id: int, payload: ShotCastAdd, db: Session = Depends(get_db)):
    shot = _get_shot_or_404(db, shot_id)
    character = db.get(Character, payload.character_id)
    if character is None:
        raise HTTPException(404, "Character not found")
    exists = db.scalar(select(ShotCharacter).where(
        ShotCharacter.shot_id == shot_id, ShotCharacter.character_id == payload.character_id))
    if exists:
        raise HTTPException(409, f"{character.name} is already in this shot")
    link = ShotCharacter(shot_id=shot_id, character_id=payload.character_id,
                         role_in_shot=payload.role_in_shot,
                         expression_note=payload.expression_note,
                         action_note=payload.action_note)
    db.add(link)
    db.commit()
    return row_to_dict(link)


@router.delete("/shots/{shot_id}/cast/{character_id}", status_code=204)
def remove_shot_cast(shot_id: int, character_id: int, db: Session = Depends(get_db)):
    link = db.scalar(select(ShotCharacter).where(
        ShotCharacter.shot_id == shot_id, ShotCharacter.character_id == character_id))
    if link is None:
        raise HTTPException(404, "Character not cast in this shot")
    db.delete(link)
    db.commit()
    return None


class ShotPropAdd(BaseModel):
    prop_id: int
    usage_notes: Optional[str] = None
    state_notes: Optional[str] = None


@router.post("/shots/{shot_id}/props", status_code=201)
def add_shot_prop(shot_id: int, payload: ShotPropAdd, db: Session = Depends(get_db)):
    shot = _get_shot_or_404(db, shot_id)
    prop = db.get(Prop, payload.prop_id)
    if prop is None:
        raise HTTPException(404, "Prop not found")
    exists = db.scalar(select(ShotProp).where(
        ShotProp.shot_id == shot_id, ShotProp.prop_id == payload.prop_id))
    if exists:
        raise HTTPException(409, "Prop already linked to this shot")
    link = ShotProp(shot_id=shot_id, prop_id=payload.prop_id,
                    usage_notes=payload.usage_notes, state_notes=payload.state_notes)
    db.add(link)
    db.commit()
    return row_to_dict(link)


@router.delete("/shots/{shot_id}/props/{prop_id}", status_code=204)
def remove_shot_prop(shot_id: int, prop_id: int, db: Session = Depends(get_db)):
    link = db.scalar(select(ShotProp).where(
        ShotProp.shot_id == shot_id, ShotProp.prop_id == prop_id))
    if link is None:
        raise HTTPException(404, "Prop not linked to this shot")
    db.delete(link)
    db.commit()
    return None


# ==========================================================================
# Shot references: storyboard images + first/last/key frames (PART 11, 12)
# ==========================================================================

class ShotRefAdd(BaseModel):
    asset_id: int
    purpose: str = "storyboard_image"
    label: Optional[str] = None
    notes: Optional[str] = None


@router.post("/shots/{shot_id}/references", status_code=201)
def add_shot_reference(shot_id: int, payload: ShotRefAdd, db: Session = Depends(get_db)):
    shot = _get_shot_or_404(db, shot_id)
    if payload.purpose not in SHOT_REFERENCE_PURPOSES:
        raise HTTPException(422, f"purpose must be one of {sorted(SHOT_REFERENCE_PURPOSES)}")
    asset = db.get(Asset, payload.asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    if payload.purpose in ("first_frame", "last_frame", "keyframe",
                           "prev_shot_frame", "next_shot_frame") and asset.status != "approved":
        raise HTTPException(
            422, f"Frame references must use APPROVED assets (asset is '{asset.status}'). "
                 "Approve the asset in the library first.")
    order = (db.scalar(select(func.max(ShotReference.order_index)).where(
        ShotReference.shot_id == shot_id)) or 0) + 1
    ref = ShotReference(shot_id=shot_id, asset_id=payload.asset_id,
                        purpose=payload.purpose, label=payload.label or asset.title,
                        notes=payload.notes, order_index=order)
    db.add(ref)
    db.commit()
    db.refresh(ref)
    return row_to_dict(ref)


@router.delete("/shots/{shot_id}/references/{reference_id}", status_code=204)
def remove_shot_reference(shot_id: int, reference_id: int, db: Session = Depends(get_db)):
    ref = db.scalar(select(ShotReference).where(
        ShotReference.id == reference_id, ShotReference.shot_id == shot_id))
    if ref is None:
        raise HTTPException(404, "Reference not found")
    db.delete(ref)
    db.commit()
    return None


# ==========================================================================
# Validation + overrides (PART 14, 20)
# ==========================================================================

@router.get("/shots/{shot_id}/validate")
def validate(shot_id: int, db: Session = Depends(get_db)):
    shot = _get_shot_or_404(db, shot_id)
    validation = validate_shot(db, shot)
    sync_continuity_records(db, shot, validation)
    return validation


class OverridePayload(BaseModel):
    check_key: str
    explanation: str = Field(min_length=3, max_length=500)


@router.post("/shots/{shot_id}/overrides")
def override_warning(shot_id: int, payload: OverridePayload, db: Session = Depends(get_db)):
    """Manually override a warning with a written explanation (audited)."""
    shot = _get_shot_or_404(db, shot_id)
    row = db.scalar(select(ShotContinuity).where(
        ShotContinuity.shot_id == shot_id, ShotContinuity.check_key == payload.check_key))
    if row is None:
        row = ShotContinuity(shot_id=shot_id, check_key=payload.check_key,
                             severity="warning", message="(manual override before re-check)")
        db.add(row)
    row.overridden = True
    row.override_explanation = payload.explanation
    row.overridden_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    validation = validate_shot(db, shot)
    sync_continuity_records(db, shot, validation)
    return validate_shot(db, shot)


# ==========================================================================
# Approval + generation readiness (PART 13, 14)
# ==========================================================================

@router.post("/shots/{shot_id}/approve")
def approve_shot(shot_id: int, note: Optional[str] = None, db: Session = Depends(get_db)):
    """Draft/needs_review/needs_revision/rejected → approved, after validation.
    Warnings may be overridden; blocking errors (unless overridden) refuse."""
    shot = _get_shot_or_404(db, shot_id)
    if shot.status not in ("draft", "needs_review", "needs_revision", "rejected", "approved"):
        raise HTTPException(409, f"Cannot approve a shot in status '{shot.status}'")
    validation = validate_shot(db, shot)
    sync_continuity_records(db, shot, validation)
    blocking = [f for f in validation["findings"]
                if f["severity"] == "error" and not f["overridden"]]
    if blocking:
        raise HTTPException(409, {
            "error": "validation_failed",
            "message": "Fix or override the blocking errors before approval.",
            "blocking": [{"key": f["key"], "message": f["message"]} for f in blocking],
        })
    previous = shot.status
    shot.status = "approved"
    # snapshot the approved creative state (never silently overwritten later)
    count = len(db.scalars(select(ShotVersion.id).where(ShotVersion.shot_id == shot_id)).all())
    snapshot = snapshot_shot(shot, count + 1, label="approved", status="approved")
    db.add(ShotVersion(shot_id=shot_id, version_number=count + 1, label="approved",
                       status="approved", snapshot=snapshot, is_current=True))
    if count:
        db.execute(ShotVersion.__table__.update().where(
            ShotVersion.shot_id == shot_id).values(is_current=False))
        db.flush()
        latest = db.scalars(select(ShotVersion).where(
            ShotVersion.shot_id == shot_id).order_by(ShotVersion.version_number.desc())).first()
        latest.is_current = True
    db.add(Approval(entity_type="shot", entity_id=str(shot_id), decision="approved",
                    note=note or f"{previous} → approved"))
    store_prompt_package(db, shot, source="approval")
    db.commit()
    db.refresh(shot)
    return {**shot_payload(db, shot), "validation": validate_shot(db, shot)}


@router.post("/shots/{shot_id}/ready-for-generation")
def ready_for_generation(shot_id: int, db: Session = Depends(get_db)):
    """approved → ready_for_generation. Requires a passing validation with no
    open warnings (or overridden ones). Phase 5 consumes these shots."""
    shot = _get_shot_or_404(db, shot_id)
    if shot.status != "approved":
        raise HTTPException(409, f"Shot must be approved first (current: '{shot.status}')")
    validation = validate_shot(db, shot)
    sync_continuity_records(db, shot, validation)
    blocking = [f for f in validation["findings"]
                if f["severity"] == "error" and not f["overridden"]]
    warnings_open = [f for f in validation["findings"]
                     if f["severity"] == "warning" and not f["overridden"]]
    if blocking:
        raise HTTPException(409, {
            "error": "validation_failed",
            "blocking": [{"key": f["key"], "message": f["message"]} for f in blocking],
        })
    if warnings_open:
        raise HTTPException(409, {
            "error": "warnings_open",
            "message": "Override the open warnings (with explanations) or fix them.",
            "warnings": [{"key": f["key"], "message": f["message"]} for f in warnings_open],
        })
    shot.status = "ready_for_generation"
    db.add(Approval(entity_type="shot", entity_id=str(shot_id), decision="approved",
                    note="ready for generation (Phase 5 payload assembled)"))
    store_prompt_package(db, shot, source="readiness")
    package = build_generation_package(db, shot)
    db.commit()
    db.refresh(shot)
    return {"shot": shot_payload(db, shot), "generation_package": package}


@router.get("/shots/{shot_id}/prompt-package")
def prompt_package_preview(shot_id: int, db: Session = Depends(get_db)):
    shot = _get_shot_or_404(db, shot_id)
    return build_prompt_package(db, shot)


@router.get("/shots/{shot_id}/generation-package")
def generation_package(shot_id: int, db: Session = Depends(get_db)):
    """The complete Phase 5 payload for this shot (readable at any time;
    marked ready only when the shot is ready_for_generation)."""
    shot = _get_shot_or_404(db, shot_id)
    return build_generation_package(db, shot)


# ==========================================================================
# Shot versions (PART 15)
# ==========================================================================

@router.get("/shots/{shot_id}/versions")
def list_versions(shot_id: int, db: Session = Depends(get_db)):
    shot = _get_shot_or_404(db, shot_id)
    versions = db.scalars(select(ShotVersion).where(
        ShotVersion.shot_id == shot_id).order_by(ShotVersion.version_number)).all()
    return {"versions": [row_to_dict(v) for v in versions]}


@router.post("/shots/{shot_id}/versions", status_code=201)
def create_version(shot_id: int, label: Optional[str] = None, db: Session = Depends(get_db)):
    """Snapshot the current creative state as a new version. Previous versions
    (including approved ones) are kept untouched."""
    shot = _get_shot_or_404(db, shot_id)
    count = len(db.scalars(select(ShotVersion.id).where(ShotVersion.shot_id == shot_id)).all())
    snapshot = snapshot_shot(shot, count + 1, label=label, status=shot.status)
    db.execute(ShotVersion.__table__.update().where(
        ShotVersion.shot_id == shot_id).values(is_current=False))
    version = ShotVersion(shot_id=shot_id, version_number=count + 1, label=label,
                          status="draft", snapshot=snapshot, is_current=True)
    db.add(version)
    db.commit()
    db.refresh(version)
    return row_to_dict(version)


@router.post("/shots/{shot_id}/versions/{version_id}/restore")
def restore_version(shot_id: int, version_id: int, db: Session = Depends(get_db)):
    """Restore creative fields from a snapshot as the working state. The
    snapshot itself is preserved; a new version is NOT auto-approved."""
    shot = _get_shot_or_404(db, shot_id)
    version = db.get(ShotVersion, version_id)
    if version is None or version.shot_id != shot_id:
        raise HTTPException(404, "Version not found")
    fields = (version.snapshot or {}).get("fields", {})
    restored = []
    for field, value in fields.items():
        if field == "status":
            continue
        setattr(shot, field, value)
        restored.append(field)
    if shot.status in ("ready_for_generation",):
        shot.status = "needs_review"  # restoring content re-opens review
    db.commit()
    return {"restored_fields": restored, "shot": shot_payload(db, shot)}


# ==========================================================================
# Phase 10 Milestone H: video version control
# ==========================================================================

@router.get("/shots/{shot_id}/video-versions")
def shot_video_version_history(shot_id: int, db: Session = Depends(get_db)):
    """Read-only VIDEO version history: results (all statuses) + failed attempts.
    (Distinct from the Phase 4 creative-snapshot /versions endpoint.)"""
    try:
        return version_history(db, shot_id)
    except VersionControlError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/shots/{shot_id}/video-versions/safety-check")
def shot_video_version_safety(shot_id: int, db: Session = Depends(get_db)):
    return version_safety_check(db, shot_id)

@router.get("/shots/{shot_id}/video-versions/{version_id}")
def shot_video_version_detail(shot_id: int, version_id: int, db: Session = Depends(get_db)):
    try:
        return version_detail(db, shot_id, version_id)
    except VersionControlError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/shots/{shot_id}/video-versions/compare/{version_a}/{version_b}")
def shot_video_version_compare(shot_id: int, version_a: int, version_b: int,
                         db: Session = Depends(get_db)):
    """Only real stored differences — no invented visual analysis."""
    try:
        return compare_versions(db, shot_id, version_a, version_b)
    except VersionControlError as error:
        raise HTTPException(404, str(error)) from error


class SelectCurrentRequest(BaseModel):
    note: Optional[str] = None


@router.post("/shots/{shot_id}/video-versions/{version_id}/select-current")
def shot_select_current(shot_id: int, version_id: int,
                        payload: SelectCurrentRequest | None = None,
                        db: Session = Depends(get_db)):
    """EXPLICIT selection of an approved version as the production version.
    Audited; never deletes/mutates history; refuses invalid versions."""
    try:
        return select_current_version(db, shot_id, version_id,
                                      payload.note if payload else None)
    except VersionControlError as error:
        raise HTTPException(409, str(error)) from error


