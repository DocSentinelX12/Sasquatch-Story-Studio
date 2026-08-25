"""Episode production API: episodes, acts, scenes, casting, props, scripts,
continuity events, checks, and storyboard readiness."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..models import (
    Act,
    Approval,
    Character,
    CharacterReference,
    ContinuityRecord,
    Episode,
    Location,
    Prop,
    Scene,
    SceneCharacter,
    SceneProp,
    ScriptElement,
)
from ..models.story import SCRIPT_ELEMENT_TYPES
from .deps import get_db, row_to_dict, slugify

router = APIRouter(prefix="/api", tags=["episodes"])

# Phase 3 lifecycle + legacy aliases (stored values are Phase 3 vocabulary)
EPISODE_STATUSES = {"draft", "development", "script", "approved", "in_production", "complete", "archived"}
EPISODE_ALIASES = {
    "planned": "draft", "outline": "development", "storyboard": "in_production",
    "shot_building": "in_production", "generating": "in_production",
    "editing": "in_production", "qc": "in_production", "exported": "complete",
    "released": "complete",
}
SCENE_STATUSES = {"draft", "needs_review", "approved", "ready_for_storyboard", "in_production", "complete"}
SCENE_ALIASES = {
    "planned": "draft", "written": "needs_review", "boarded": "ready_for_storyboard",
    "shot_ready": "ready_for_storyboard", "generating": "in_production",
}
CONTINUITY_KINDS = {
    "event", "character_location", "relationship", "prop", "injury", "clothing",
    "weather", "time_of_day", "discovery", "open_thread", "canon_fact",
    "object", "location_change", "revelation", "unresolved_thread", "resolved_thread", "story_event",
}
SCRIPT_STATUSES = {"draft", "review", "approved"}


def norm(value: str, aliases: dict) -> str:
    return aliases.get(value, value)


# ==========================================================================
# Episodes
# ==========================================================================

class EpisodeCreate(BaseModel):
    project_id: int
    number: Optional[int] = None
    title: str = Field(min_length=1, max_length=160)
    slug: Optional[str] = None
    season_number: Optional[int] = None
    status: str = "draft"
    logline: Optional[str] = None
    premise: Optional[str] = None
    summary: Optional[str] = None
    target_length_minutes: float = 8.0


class EpisodeUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    status: Optional[str] = None
    logline: Optional[str] = None
    premise: Optional[str] = None
    summary: Optional[str] = None
    target_length_minutes: Optional[float] = None
    script_status: Optional[str] = None


@router.get("/episodes")
def list_episodes(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = select(Episode).order_by(Episode.project_id, Episode.number)
    if project_id is not None:
        query = query.where(Episode.project_id == project_id)
    episodes = db.scalars(query).all()
    result = []
    for episode in episodes:
        scene_count = db.scalar(select(func.count(Scene.id)).where(Scene.episode_id == episode.id)) or 0
        script_element_count = db.scalar(
            select(func.count(ScriptElement.id)).where(ScriptElement.episode_id == episode.id)
        ) or 0
        result.append({
            **row_to_dict(episode),
            "scene_count": scene_count,
            "script_element_count": script_element_count,
        })
    return {"episodes": result}


@router.post("/episodes", status_code=201)
def create_episode(payload: EpisodeCreate, db: Session = Depends(get_db)):
    status = norm(payload.status, EPISODE_ALIASES)
    if status not in EPISODE_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(EPISODE_STATUSES)}")
    from ..models import Season

    season_id = None
    if payload.season_number is not None:
        season = db.scalar(select(Season).where(
            Season.project_id == payload.project_id, Season.number == payload.season_number))
        if season is None:
            season = Season(project_id=payload.project_id, number=payload.season_number,
                            title=f"Season {payload.season_number}", status="planned")
            db.add(season)
            db.flush()
        season_id = season.id
    number = payload.number or (db.scalar(
        select(func.max(Episode.number)).where(Episode.project_id == payload.project_id)) or 0) + 1
    if db.scalar(select(Episode).where(Episode.project_id == payload.project_id, Episode.number == number)):
        raise HTTPException(409, f"Episode number {number} already exists in this project")
    episode = Episode(
        project_id=payload.project_id, season_id=season_id, number=number,
        title=payload.title, slug=payload.slug or slugify(payload.title),
        status=status, logline=payload.logline, premise=payload.premise,
        summary=payload.summary, target_length_minutes=payload.target_length_minutes,
    )
    db.add(episode)
    db.commit()
    db.refresh(episode)
    return row_to_dict(episode)


@router.get("/episodes/{episode_id}")
def get_episode(episode_id: int, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(404, "Episode not found")
    acts = db.scalars(select(Act).where(Act.episode_id == episode_id).order_by(Act.number)).all()
    scenes = db.scalars(
        select(Scene).where(Scene.episode_id == episode_id)
        .options(joinedload(Scene.location), joinedload(Scene.cast), joinedload(Scene.prop_links))
        .order_by(Scene.order_index)
    ).unique().all()
    scene_payload = []
    for scene in scenes:
        scene_payload.append(scene_payload_dict(db, scene))
    return {
        **row_to_dict(episode),
        "acts": [row_to_dict(a) for a in acts],
        "scenes": scene_payload,
    }


def scene_payload_dict(db: Session, scene: Scene) -> dict:
    cast = db.scalars(
        select(SceneCharacter).where(SceneCharacter.scene_id == scene.id)
        .options(joinedload(SceneCharacter.character))
    ).all()
    prop_links = db.scalars(
        select(SceneProp).where(SceneProp.scene_id == scene.id)
        .options(joinedload(SceneProp.prop))
    ).all()
    script = db.scalars(
        select(ScriptElement).where(ScriptElement.scene_id == scene.id)
        .order_by(ScriptElement.order_index, ScriptElement.id)
    ).all()
    return {
        **row_to_dict(scene),
        "location_name": scene.location.name if scene.location else None,
        "cast": [
            {**row_to_dict(link), "character": {
                "id": link.character.id, "name": link.character.name,
                "char_ref": link.character.char_ref, "species": link.character.species,
            } if link.character else None}
            for link in cast
        ],
        "props": [
            {**row_to_dict(link), "prop": {
                "id": link.prop.id, "name": link.prop.name,
            } if link.prop else None}
            for link in prop_links
        ],
        "script": [row_to_dict(e) for e in script],
    }


@router.patch("/episodes/{episode_id}")
def update_episode(episode_id: int, payload: EpisodeUpdate, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(404, "Episode not found")
    if payload.status is not None:
        status = norm(payload.status, EPISODE_ALIASES)
        if status not in EPISODE_STATUSES:
            raise HTTPException(422, f"status must be one of {sorted(EPISODE_STATUSES)}")
        payload.status = status
        if status == "approved":
            db.add(Approval(entity_type="episode", entity_id=str(episode_id), decision="approved"))
    if payload.script_status is not None:
        if payload.script_status not in SCRIPT_STATUSES:
            raise HTTPException(422, f"script_status must be one of {sorted(SCRIPT_STATUSES)}")
        if payload.script_status == "approved":
            db.add(Approval(entity_type="script", entity_id=str(episode_id), decision="approved",
                            note="script approved"))
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(episode, field, value)
    db.commit()
    db.refresh(episode)
    return row_to_dict(episode)


# ==========================================================================
# Acts (PART 6)
# ==========================================================================

class ActCreate(BaseModel):
    episode_id: int
    number: Optional[int] = None
    title: str = ""
    purpose: Optional[str] = None
    summary: Optional[str] = None
    beginning: Optional[str] = None
    middle: Optional[str] = None
    ending: Optional[str] = None


class ActUpdate(BaseModel):
    title: Optional[str] = None
    purpose: Optional[str] = None
    summary: Optional[str] = None
    beginning: Optional[str] = None
    middle: Optional[str] = None
    ending: Optional[str] = None
    number: Optional[int] = None


@router.post("/acts", status_code=201)
def create_act(payload: ActCreate, db: Session = Depends(get_db)):
    if db.get(Episode, payload.episode_id) is None:
        raise HTTPException(404, "Episode not found")
    number = payload.number or (db.scalar(
        select(func.max(Act.number)).where(Act.episode_id == payload.episode_id)) or 0) + 1
    act = Act(episode_id=payload.episode_id, number=number, title=payload.title or f"Act {number}",
              purpose=payload.purpose, summary=payload.summary,
              beginning=payload.beginning, middle=payload.middle, ending=payload.ending)
    db.add(act)
    db.commit()
    db.refresh(act)
    return row_to_dict(act)


@router.patch("/acts/{act_id}")
def update_act(act_id: int, payload: ActUpdate, db: Session = Depends(get_db)):
    act = db.get(Act, act_id)
    if act is None:
        raise HTTPException(404, "Act not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(act, field, value)
    db.commit()
    db.refresh(act)
    return row_to_dict(act)


@router.delete("/acts/{act_id}", status_code=204)
def delete_act(act_id: int, db: Session = Depends(get_db)):
    act = db.get(Act, act_id)
    if act is None:
        raise HTTPException(404, "Act not found")
    # scenes fall back to episode-level (act_id NULL via SET NULL)
    db.delete(act)
    db.commit()
    return None


# ==========================================================================
# Scenes (PART 7)
# ==========================================================================

class SceneCreate(BaseModel):
    episode_id: int
    act_id: Optional[int] = None
    title: str = ""
    location_id: Optional[int] = None
    time_of_day: Optional[str] = None
    weather: Optional[str] = None
    story_purpose: Optional[str] = None
    summary: Optional[str] = None
    visual_action: Optional[str] = None
    emotional_tone: Optional[str] = None
    visual_direction: Optional[str] = None
    continuity_notes: Optional[str] = None
    estimated_duration_seconds: Optional[float] = None


class SceneUpdate(BaseModel):
    title: Optional[str] = None
    act_id: Optional[int] = None
    location_id: Optional[int] = None
    time_of_day: Optional[str] = None
    weather: Optional[str] = None
    story_purpose: Optional[str] = None
    summary: Optional[str] = None
    visual_action: Optional[str] = None
    emotional_tone: Optional[str] = None
    visual_direction: Optional[str] = None
    continuity_notes: Optional[str] = None
    dependency_notes: Optional[str] = None
    estimated_duration_seconds: Optional[float] = None
    status: Optional[str] = None


@router.post("/scenes", status_code=201)
def create_scene(payload: SceneCreate, db: Session = Depends(get_db)):
    if db.get(Episode, payload.episode_id) is None:
        raise HTTPException(404, "Episode not found")
    if payload.location_id is not None and db.get(Location, payload.location_id) is None:
        raise HTTPException(422, "Unknown location")
    order = (db.scalar(select(func.max(Scene.order_index)).where(
        Scene.episode_id == payload.episode_id)) or 0) + 1
    number = (db.scalar(select(func.count(Scene.id)).where(
        Scene.episode_id == payload.episode_id)) or 0) + 1
    scene = Scene(
        episode_id=payload.episode_id, act_id=payload.act_id, number=number,
        scene_ref=f"SC-{number:03d}", title=payload.title, slug=slugify(payload.title or f"scene-{number}"),
        location_id=payload.location_id, time_of_day=payload.time_of_day,
        weather=payload.weather, story_purpose=payload.story_purpose,
        summary=payload.summary, visual_action=payload.visual_action,
        emotional_tone=payload.emotional_tone, visual_direction=payload.visual_direction,
        continuity_notes=payload.continuity_notes,
        estimated_duration_seconds=payload.estimated_duration_seconds,
        status="draft", order_index=order,
    )
    db.add(scene)
    db.commit()
    db.refresh(scene)
    return scene_payload_dict(db, scene)


@router.get("/scenes")
def list_scenes(
    episode_id: Optional[int] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = select(Scene).options(joinedload(Scene.episode), joinedload(Scene.location))
    if episode_id:
        query = query.where(Scene.episode_id == episode_id)
    if status:
        query = query.where(Scene.status == norm(status, SCENE_ALIASES))
    if q:
        like = f"%{q.lower()}%"
        query = query.where(func.lower(Scene.title).like(like) | func.lower(Scene.summary).like(like) |
                            func.lower(Scene.visual_action).like(like))
    scenes = db.scalars(query.order_by(Scene.episode_id, Scene.order_index)).all()
    return {"scenes": [scene_payload_dict(db, s) for s in scenes]}


@router.get("/scenes/{scene_id}")
def get_scene(scene_id: int, db: Session = Depends(get_db)):
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    return scene_payload_dict(db, scene)


@router.patch("/scenes/{scene_id}")
def update_scene(scene_id: int, payload: SceneUpdate, db: Session = Depends(get_db)):
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    if payload.status is not None:
        status = norm(payload.status, SCENE_ALIASES)
        if status not in SCENE_STATUSES:
            raise HTTPException(422, f"status must be one of {sorted(SCENE_STATUSES)}")
        if status in ("approved", "ready_for_storyboard") and scene.status not in (
                "draft", "needs_review", "approved", "ready_for_storyboard"):
            raise HTTPException(409, f"Cannot approve a scene in status '{scene.status}'")
        if status == "approved":
            db.add(Approval(entity_type="scene", entity_id=str(scene_id), decision="approved"))
        payload.status = status
    if payload.location_id is not None and db.get(Location, payload.location_id) is None:
        raise HTTPException(422, "Unknown location")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(scene, field, value)
    db.commit()
    db.refresh(scene)
    return scene_payload_dict(db, scene)


@router.delete("/scenes/{scene_id}", status_code=204)
def delete_scene(scene_id: int, db: Session = Depends(get_db)):
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    if scene.status in ("ready_for_storyboard", "in_production", "complete"):
        raise HTTPException(409, f"Scene in status '{scene.status}' cannot be deleted")
    db.delete(scene)
    db.commit()
    return None


class ReorderPayload(BaseModel):
    scene_ids: list[int] = Field(min_length=1)


@router.post("/episodes/{episode_id}/scenes/reorder")
def reorder_scenes(episode_id: int, payload: ReorderPayload, db: Session = Depends(get_db)):
    """Set scene order explicitly; renumbers order_index and scene numbers."""
    scenes = db.scalars(select(Scene).where(Scene.episode_id == episode_id)).all()
    by_id = {s.id: s for s in scenes}
    unknown = [sid for sid in payload.scene_ids if sid not in by_id]
    if unknown:
        raise HTTPException(422, f"Scene ids not in this episode: {unknown}")
    order_map = {sid: idx + 1 for idx, sid in enumerate(payload.scene_ids)}
    for scene in scenes:
        scene.order_index = order_map.get(scene.id, len(payload.scene_ids) + scene.order_index)
    # renumber scene_ref/number by new order
    for scene in sorted(scenes, key=lambda s: s.order_index):
        pass
    for idx, scene in enumerate(sorted(scenes, key=lambda s: s.order_index), start=1):
        scene.number = idx
        scene.scene_ref = f"SC-{idx:03d}"
    db.commit()
    return {"scenes": [scene_payload_dict(db, s) for s in sorted(scenes, key=lambda x: x.order_index)]}


# ==========================================================================
# Scene casting (PART 8)
# ==========================================================================

class CastAdd(BaseModel):
    character_id: int
    role_in_scene: Optional[str] = None


@router.post("/scenes/{scene_id}/cast", status_code=201)
def add_cast(scene_id: int, payload: CastAdd, db: Session = Depends(get_db)):
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    character = db.get(Character, payload.character_id)
    if character is None:
        raise HTTPException(404, "Character not found")
    if character.project_id != scene.episode.project_id if scene.episode else False:
        raise HTTPException(422, "Character belongs to a different project")
    exists = db.scalar(select(SceneCharacter).where(
        SceneCharacter.scene_id == scene_id, SceneCharacter.character_id == payload.character_id))
    if exists:
        raise HTTPException(409, f"{character.name} is already in this scene")
    link = SceneCharacter(scene_id=scene_id, character_id=payload.character_id,
                          role_in_scene=payload.role_in_scene)
    db.add(link)
    db.commit()
    db.refresh(link)
    return row_to_dict(link)


@router.delete("/scenes/{scene_id}/cast/{character_id}", status_code=204)
def remove_cast(scene_id: int, character_id: int, db: Session = Depends(get_db)):
    link = db.scalar(select(SceneCharacter).where(
        SceneCharacter.scene_id == scene_id, SceneCharacter.character_id == character_id))
    if link is None:
        raise HTTPException(404, "Character not cast in this scene")
    db.delete(link)
    db.commit()
    return None


@router.get("/scenes/{scene_id}/cast/{character_id}/profile")
def cast_profile(scene_id: int, character_id: int, db: Session = Depends(get_db)):
    """Approved character information for the scene builder (feeds Phase 4
    reference packages)."""
    character = db.get(Character, character_id)
    if character is None:
        raise HTTPException(404, "Character not found")
    references = db.scalars(
        select(CharacterReference).where(
            CharacterReference.character_id == character_id,
            CharacterReference.approval_status == "approved",
        ).options(joinedload(CharacterReference.asset))
    ).all()
    cast_rows = db.scalars(select(SceneCharacter).where(
        SceneCharacter.scene_id == scene_id)).all()
    cast_ids = {r.character_id for r in cast_rows}
    from ..models import CharacterRelationship
    rel_out = []
    for rel in db.scalars(select(CharacterRelationship).where(
            CharacterRelationship.character_id == character_id)).all():
        target = db.get(Character, rel.related_character_id)
        rel_out.append({
            "kind": rel.kind, "notes": rel.notes,
            "with_character": target.name if target else None,
            "in_scene": rel.related_character_id in cast_ids,
        })
    return {
        "character": row_to_dict(character),
        "approved_references": [
            {"purpose": r.purpose, "label": r.label,
             "asset_id": r.asset.id if r.asset else None,
             "repo_path": r.asset.repo_path if r.asset else None}
            for r in references if r.asset
        ],
        "relationships": rel_out,
    }


# ==========================================================================
# Scene props (PART 10)
# ==========================================================================

class ScenePropAdd(BaseModel):
    prop_id: int
    usage_notes: Optional[str] = None


@router.post("/scenes/{scene_id}/props", status_code=201)
def add_scene_prop(scene_id: int, payload: ScenePropAdd, db: Session = Depends(get_db)):
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    prop = db.get(Prop, payload.prop_id)
    if prop is None:
        raise HTTPException(404, "Prop not found")
    exists = db.scalar(select(SceneProp).where(
        SceneProp.scene_id == scene_id, SceneProp.prop_id == payload.prop_id))
    if exists:
        raise HTTPException(409, "Prop already linked to this scene")
    link = SceneProp(scene_id=scene_id, prop_id=payload.prop_id,
                     usage_notes=payload.usage_notes)
    db.add(link)
    db.commit()
    db.refresh(link)
    return row_to_dict(link)


@router.delete("/scenes/{scene_id}/props/{prop_id}", status_code=204)
def remove_scene_prop(scene_id: int, prop_id: int, db: Session = Depends(get_db)):
    link = db.scalar(select(SceneProp).where(
        SceneProp.scene_id == scene_id, SceneProp.prop_id == prop_id))
    if link is None:
        raise HTTPException(404, "Prop not linked to this scene")
    db.delete(link)
    db.commit()
    return None


# ==========================================================================
# Script elements (PART 11 + 12)
# ==========================================================================

class ElementCreate(BaseModel):
    scene_id: int
    element_type: str
    text: str = ""
    character_id: Optional[int] = None
    character_name: Optional[str] = None
    narrator_name: Optional[str] = None
    timing_notes: Optional[str] = None
    notes: Optional[str] = None


class ElementUpdate(BaseModel):
    element_type: Optional[str] = None
    text: Optional[str] = None
    character_id: Optional[int] = None
    character_name: Optional[str] = None
    narrator_name: Optional[str] = None
    timing_notes: Optional[str] = None
    notes: Optional[str] = None
    order_index: Optional[float] = None


@router.post("/script-elements", status_code=201)
def create_element(payload: ElementCreate, db: Session = Depends(get_db)):
    scene = db.get(Scene, payload.scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    if payload.element_type not in SCRIPT_ELEMENT_TYPES:
        raise HTTPException(422, f"element_type must be one of {sorted(SCRIPT_ELEMENT_TYPES)}")
    if payload.character_id is not None and db.get(Character, payload.character_id) is None:
        raise HTTPException(422, "Unknown character")
    order = (db.scalar(select(func.max(ScriptElement.order_index)).where(
        ScriptElement.scene_id == payload.scene_id)) or 0) + 1
    element = ScriptElement(
        scene_id=payload.scene_id, episode_id=scene.episode_id, order_index=order,
        element_type=payload.element_type, text=payload.text,
        character_id=payload.character_id, character_name=payload.character_name,
        narrator_name=payload.narrator_name, timing_notes=payload.timing_notes,
        notes=payload.notes,
    )
    db.add(element)
    db.commit()
    db.refresh(element)
    return row_to_dict(element)


@router.patch("/script-elements/{element_id}")
def update_element(element_id: int, payload: ElementUpdate, db: Session = Depends(get_db)):
    element = db.get(ScriptElement, element_id)
    if element is None:
        raise HTTPException(404, "Script element not found")
    if payload.element_type is not None and payload.element_type not in SCRIPT_ELEMENT_TYPES:
        raise HTTPException(422, f"element_type must be one of {sorted(SCRIPT_ELEMENT_TYPES)}")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(element, field, value)
    db.commit()
    db.refresh(element)
    return row_to_dict(element)


@router.delete("/script-elements/{element_id}", status_code=204)
def delete_element(element_id: int, db: Session = Depends(get_db)):
    element = db.get(ScriptElement, element_id)
    if element is None:
        raise HTTPException(404, "Script element not found")
    db.delete(element)
    db.commit()
    return None


class ElementMove(BaseModel):
    direction: str = Field(pattern="^(up|down)")


@router.post("/script-elements/{element_id}/move")
def move_element(element_id: int, payload: ElementMove, db: Session = Depends(get_db)):
    """Swap an element with its neighbour within the scene."""
    element = db.get(ScriptElement, element_id)
    if element is None:
        raise HTTPException(404, "Script element not found")
    siblings = db.scalars(select(ScriptElement).where(
        ScriptElement.scene_id == element.scene_id)
        .order_by(ScriptElement.order_index, ScriptElement.id)).all()
    index = siblings.index(element)
    swap_with = siblings[index - 1] if payload.direction == "up" and index > 0 else \
                siblings[index + 1] if payload.direction == "down" and index < len(siblings) - 1 else None
    if swap_with is not None:
        element.order_index, swap_with.order_index = swap_with.order_index, element.order_index
        # ensure strict ordering
        for i, sib in enumerate(db.scalars(select(ScriptElement).where(
                ScriptElement.scene_id == element.scene_id)
                .order_by(ScriptElement.order_index, ScriptElement.id)).all(), start=1):
            sib.order_index = float(i)
        db.commit()
    return {"script": [row_to_dict(e) for e in db.scalars(select(ScriptElement).where(
        ScriptElement.scene_id == element.scene_id).order_by(ScriptElement.order_index)).all()]}


@router.post("/script-elements/{element_id}/duplicate", status_code=201)
def duplicate_element(element_id: int, db: Session = Depends(get_db)):
    element = db.get(ScriptElement, element_id)
    if element is None:
        raise HTTPException(404, "Script element not found")
    clone = ScriptElement(
        scene_id=element.scene_id, episode_id=element.episode_id,
        order_index=element.order_index + 0.5,
        element_type=element.element_type, text=element.text,
        character_id=element.character_id, character_name=element.character_name,
        narrator_name=element.narrator_name, timing_notes=element.timing_notes,
        notes=element.notes,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return row_to_dict(clone)


class ElementTransfer(BaseModel):
    target_scene_id: int


@router.post("/script-elements/{element_id}/transfer")
def transfer_element(element_id: int, payload: ElementTransfer, db: Session = Depends(get_db)):
    """Move a line to another scene (same episode)."""
    element = db.get(ScriptElement, element_id)
    if element is None:
        raise HTTPException(404, "Script element not found")
    target = db.get(Scene, payload.target_scene_id)
    if target is None:
        raise HTTPException(404, "Target scene not found")
    if target.episode_id != element.episode_id:
        raise HTTPException(422, "Lines can only move between scenes of the same episode")
    element.scene_id = target.id
    element.order_index = (db.scalar(select(func.max(ScriptElement.order_index)).where(
        ScriptElement.scene_id == target.id)) or 0) + 1
    db.commit()
    return row_to_dict(element)


# ==========================================================================
# Episode continuity events (PART 14)
# ==========================================================================

class EventCreate(BaseModel):
    kind: str
    summary: str = Field(min_length=1, max_length=400)
    details: Optional[dict] = None
    scene_id: Optional[int] = None


class EventUpdate(BaseModel):
    summary: Optional[str] = None
    details: Optional[dict] = None
    status: Optional[str] = None


@router.get("/episodes/{episode_id}/continuity")
def list_events(episode_id: int, db: Session = Depends(get_db)):
    events = db.scalars(select(ContinuityRecord).where(
        ContinuityRecord.episode_id == episode_id).order_by(ContinuityRecord.id)).all()
    return {"events": [row_to_dict(e) for e in events]}


@router.post("/episodes/{episode_id}/continuity", status_code=201)
def create_event(episode_id: int, payload: EventCreate, db: Session = Depends(get_db)):
    if db.get(Episode, episode_id) is None:
        raise HTTPException(404, "Episode not found")
    if payload.kind not in CONTINUITY_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(CONTINUITY_KINDS)}")
    event = ContinuityRecord(
        project_id=db.get(Episode, episode_id).project_id, episode_id=episode_id,
        kind=payload.kind, summary=payload.summary, details=payload.details,
        status="draft",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return row_to_dict(event)


@router.patch("/continuity/{event_id}")
def update_event(event_id: int, payload: EventUpdate, db: Session = Depends(get_db)):
    event = db.get(ContinuityRecord, event_id)
    if event is None:
        raise HTTPException(404, "Event not found")
    if payload.status is not None and payload.status not in ("draft", "canon"):
        raise HTTPException(422, "status must be draft | canon")
    if payload.status == "canon":
        db.add(Approval(entity_type="continuity", entity_id=str(event_id), decision="approved",
                        note="continuity event made canon"))
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(event, field, value)
    db.commit()
    db.refresh(event)
    return row_to_dict(event)


@router.post("/continuity/{event_id}/resolve")
def resolve_event(event_id: int, db: Session = Depends(get_db)):
    """unresolved_thread → resolved_thread (recorded, never auto-canonized)."""
    event = db.get(ContinuityRecord, event_id)
    if event is None:
        raise HTTPException(404, "Event not found")
    if event.kind != "unresolved_thread":
        raise HTTPException(409, f"Only unresolved threads can be resolved (kind={event.kind})")
    event.kind = "resolved_thread"
    db.commit()
    db.refresh(event)
    return row_to_dict(event)


# ==========================================================================
# Continuity warnings (PART 13) + storyboard readiness (PART 17)
# ==========================================================================

FOOTWEAR_PATTERN = ("shoes", "boots", "socks", "sandals", "slippers", "sneakers", "heels")
FOOTWEAR_ALLOW = ("no shoes", "without shoes", "barefoot", "not wearing")


@router.get("/scenes/{scene_id}/continuity-check")
def continuity_check(scene_id: int, db: Session = Depends(get_db)):
    """Rule-based draft checks against known canon. Warnings only —
    canon is never modified automatically."""
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    warnings: list[dict] = []
    info: list[dict] = []

    cast = db.scalars(select(SceneCharacter).where(
        SceneCharacter.scene_id == scene_id).options(joinedload(SceneCharacter.character))).all()
    script = db.scalars(select(ScriptElement).where(
        ScriptElement.scene_id == scene_id)).all()
    text_blob = " ".join(filter(None, [
        scene.summary, scene.visual_action, scene.visual_direction,
        *(e.text for e in script),
    ])).lower()

    # 1. barefoot canon: any footwear mention is a violation unless negated
    for word in FOOTWEAR_PATTERN:
        if word in text_blob:
            idx = text_blob.find(word)
            context = text_blob[max(0, idx - 25):idx + len(word) + 5]
            if not any(allow in context for allow in FOOTWEAR_ALLOW):
                warnings.append({
                    "severity": "violation",
                    "rule": "barefoot-canon",
                    "message": f"Possible footwear mention (\"{word}\") — ALL CHARACTERS ARE ALWAYS BAREFOOT.",
                })
                break

    # 2. cast checks
    for link in cast:
        character = link.character
        if character is None:
            continue
        if character.approval_status != "approved":
            warnings.append({
                "severity": "warning",
                "rule": "character-approval",
                "message": f"{character.name} is not canon-approved yet.",
            })
        approved_refs = db.scalar(select(func.count(CharacterReference.id)).where(
            CharacterReference.character_id == character.id,
            CharacterReference.approval_status == "approved"))
        if not approved_refs:
            info.append({
                "severity": "info",
                "rule": "character-references",
                "message": f"{character.name} has no approved reference images yet (needed for Phase 4 packages).",
            })

    # 3. scene completeness
    if not cast:
        warnings.append({"severity": "warning", "rule": "cast-empty",
                         "message": "Scene has no characters cast."})
    if scene.location_id is None:
        info.append({"severity": "info", "rule": "location-missing",
                     "message": "No location set for this scene."})
    if not scene.time_of_day:
        info.append({"severity": "info", "rule": "time-missing",
                     "message": "No time of day set."})
    if not script:
        info.append({"severity": "info", "rule": "script-empty",
                     "message": "Scene has no script lines yet."})

    return {"scene_id": scene_id, "warnings": warnings, "info": info,
            "checked_fields": ["barefoot canon", "character approval", "approved references",
                                "cast", "location", "time of day", "script"]}


@router.post("/scenes/{scene_id}/ready-for-storyboard")
def ready_for_storyboard(scene_id: int, db: Session = Depends(get_db)):
    """Approve + mark ready; assembles the Phase 4 reference package."""
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    if scene.status not in ("draft", "needs_review", "approved"):
        raise HTTPException(409, f"Scene must be approved first (current: {scene.status})")
    missing = []
    if scene.location_id is None:
        missing.append("location")
    if not scene.cast:
        missing.append("cast")
    if missing:
        raise HTTPException(409, {"error": "incomplete_scene", "missing": missing})
    if scene.status != "approved":
        scene.status = "approved"
    db.flush()
    package = build_storyboard_package(db, scene)
    scene.status = "ready_for_storyboard"
    db.add(Approval(entity_type="scene", entity_id=str(scene_id), decision="approved",
                    note="ready for storyboard (Phase 4 package assembled)"))
    db.commit()
    db.refresh(scene)
    return {"scene": row_to_dict(scene), "package": package}


@router.get("/scenes/{scene_id}/package")
def get_package(scene_id: int, db: Session = Depends(get_db)):
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, "Scene not found")
    return build_storyboard_package(db, scene)


def build_storyboard_package(db: Session, scene: Scene) -> dict:
    """Everything Phase 4 needs: scene info, cast with approved references,
    location, props, script, direction, continuity."""
    episode = db.get(Episode, scene.episode_id)
    location = db.get(Location, scene.location_id) if scene.location_id else None
    cast_payload = []
    for link in db.scalars(select(SceneCharacter).where(
            SceneCharacter.scene_id == scene.id)).all():
        character = link.character
        if character is None:
            continue
        refs = db.scalars(select(CharacterReference).where(
            CharacterReference.character_id == character.id,
            CharacterReference.approval_status == "approved",
        ).options(joinedload(CharacterReference.asset))).all()
        cast_payload.append({
            "character_id": character.char_ref or character.id,
            "name": character.name,
            "role_in_scene": link.role_in_scene,
            "appearance": character.standard_appearance,
            "outfit": character.current_outfit,
            "standard_props": character.standard_props,
            "personality": character.personality_summary,
            "visual_rules": character.visual_rules,
            "never_changes": character.never_changes,
            "master_visual_prompt": character.master_visual_prompt,
            "negative_prompt": character.negative_prompt,
            "approved_references": [
                {"purpose": r.purpose, "label": r.label,
                 "asset_id": r.asset.id, "repo_path": r.asset.repo_path,
                 "sha256": r.asset.sha256}
                for r in refs if r.asset
            ],
        })
    props_payload = []
    for link in db.scalars(select(SceneProp).where(
            SceneProp.scene_id == scene.id)).all():
        prop = link.prop
        if prop is None:
            continue
        props_payload.append({
            "name": prop.name, "description": prop.description,
            "owner_character_id": prop.owner_character_id,
            "continuity_notes": prop.continuity_notes,
        })
    script = db.scalars(select(ScriptElement).where(
        ScriptElement.scene_id == scene.id).order_by(ScriptElement.order_index)).all()
    return {
        "scene": {
            "scene_ref": scene.scene_ref, "number": scene.number, "title": scene.title,
            "location": {"name": location.name, "environment": location.environment,
                         "visual_rules": location.visual_rules,
                         "time_of_day_notes": location.time_of_day_notes,
                         "weather_notes": location.weather_notes} if location else None,
            "time_of_day": scene.time_of_day, "weather": scene.weather,
            "story_purpose": scene.story_purpose, "summary": scene.summary,
            "emotional_tone": scene.emotional_tone,
            "visual_direction": scene.visual_direction,
            "continuity_notes": scene.continuity_notes,
            "dependency_notes": scene.dependency_notes,
            "estimated_duration_seconds": scene.estimated_duration_seconds,
        },
        "episode": {"id": scene.episode_id, "number": episode.number if episode else None,
                    "title": episode.title if episode else None},
        "characters": cast_payload,
        "props": props_payload,
        "script": [
            {"type": e.element_type, "speaker": e.character.name if e.character else e.character_name,
             "narrator": e.narrator_name, "text": e.text,
             "timing_notes": e.timing_notes, "order": e.order_index}
            for e in script
        ],
        "barefoot_rule": "ALL CHARACTERS ARE ALWAYS BAREFOOT. NO SHOES, SOCKS, BOOTS, SANDALS, SLIPPERS, OR ANY OTHER FOOTWEAR.",
    }
