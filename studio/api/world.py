"""World API: reusable locations and props (PART 9 + 10)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..models import Approval, Asset, Character, Location, Prop, Scene
from .deps import get_db, row_to_dict

router = APIRouter(prefix="/api/world", tags=["world"])

APPROVAL_STATUSES = {"registered", "pending_approval", "approved"}


# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------

class LocationCreate(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=160)
    kind: Optional[str] = None
    description: Optional[str] = None
    environment: Optional[str] = None
    time_of_day_notes: Optional[str] = None
    weather_notes: Optional[str] = None
    visual_rules: Optional[list] = None
    continuity_notes: Optional[str] = None
    loc_ref: Optional[str] = None


class LocationUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    description: Optional[str] = None
    environment: Optional[str] = None
    time_of_day_notes: Optional[str] = None
    weather_notes: Optional[str] = None
    visual_rules: Optional[list] = None
    continuity_notes: Optional[str] = None
    approval_status: Optional[str] = None


@router.get("/locations")
def list_locations(project_id: Optional[int] = None, q: Optional[str] = None,
                   db: Session = Depends(get_db)):
    query = select(Location)
    if project_id:
        query = query.where(Location.project_id == project_id)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(
            func.lower(Location.name).like(like),
            func.lower(Location.description).like(like),
            func.lower(Location.environment).like(like),
        ))
    locations = db.scalars(query.order_by(Location.name)).all()
    result = []
    for location in locations:
        usage = db.scalar(select(func.count(Scene.id)).where(Scene.location_id == location.id)) or 0
        asset_count = db.scalar(select(func.count(Asset.id)).where(Asset.location_id == location.id)) or 0
        result.append({**row_to_dict(location), "scene_usage": usage, "asset_count": asset_count})
    return {"locations": result}


@router.post("/locations", status_code=201)
def create_location(payload: LocationCreate, db: Session = Depends(get_db)):
    location = Location(
        project_id=payload.project_id, name=payload.name, kind=payload.kind,
        description=payload.description, environment=payload.environment,
        time_of_day_notes=payload.time_of_day_notes,
        weather_notes=payload.weather_notes, visual_rules=payload.visual_rules,
        continuity_notes=payload.continuity_notes, loc_ref=payload.loc_ref,
        approval_status="registered",
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return row_to_dict(location)


@router.patch("/locations/{location_id}")
def update_location(location_id: int, payload: LocationUpdate, db: Session = Depends(get_db)):
    location = db.get(Location, location_id)
    if location is None:
        raise HTTPException(404, "Location not found")
    if payload.approval_status is not None:
        if payload.approval_status not in APPROVAL_STATUSES:
            raise HTTPException(422, f"approval_status must be one of {sorted(APPROVAL_STATUSES)}")
        if payload.approval_status == "approved":
            db.add(Approval(entity_type="location", entity_id=str(location_id), decision="approved"))
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(location, field, value)
    db.commit()
    db.refresh(location)
    return row_to_dict(location)


@router.delete("/locations/{location_id}", status_code=204)
def delete_location(location_id: int, db: Session = Depends(get_db)):
    location = db.get(Location, location_id)
    if location is None:
        raise HTTPException(404, "Location not found")
    used = db.scalar(select(func.count(Scene.id)).where(Scene.location_id == location_id)) or 0
    if used:
        raise HTTPException(409, f"Location is used by {used} scene(s) — archive instead")
    db.delete(location)
    db.commit()
    return None


# --------------------------------------------------------------------------
# Props
# --------------------------------------------------------------------------

class PropCreate(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=160)
    description: Optional[str] = None
    owner_character_id: Optional[int] = None
    continuity_notes: Optional[str] = None


class PropUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    owner_character_id: Optional[int] = None
    continuity_notes: Optional[str] = None
    approval_status: Optional[str] = None


@router.get("/props")
def list_props(project_id: Optional[int] = None, q: Optional[str] = None,
               db: Session = Depends(get_db)):
    from ..models import SceneProp

    query = select(Prop).options(joinedload(Prop.owner))
    if project_id:
        query = query.where(Prop.project_id == project_id)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(Prop.name).like(like), func.lower(Prop.description).like(like)))
    props = db.scalars(query.order_by(Prop.name)).all()
    result = []
    for prop in props:
        usage = db.scalar(select(func.count(SceneProp.prop_id)).where(SceneProp.prop_id == prop.id)) or 0
        result.append({
            **row_to_dict(prop),
            "owner_name": prop.owner.name if prop.owner else None,
            "scene_usage": usage,
        })
    return {"props": result}


@router.post("/props", status_code=201)
def create_prop(payload: PropCreate, db: Session = Depends(get_db)):
    if payload.owner_character_id is not None and db.get(Character, payload.owner_character_id) is None:
        raise HTTPException(422, "Unknown owner character")
    prop = Prop(
        project_id=payload.project_id, name=payload.name,
        description=payload.description, owner_character_id=payload.owner_character_id,
        continuity_notes=payload.continuity_notes, approval_status="registered",
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return row_to_dict(prop)


@router.patch("/props/{prop_id}")
def update_prop(prop_id: int, payload: PropUpdate, db: Session = Depends(get_db)):
    prop = db.get(Prop, prop_id)
    if prop is None:
        raise HTTPException(404, "Prop not found")
    if payload.approval_status is not None:
        if payload.approval_status not in APPROVAL_STATUSES:
            raise HTTPException(422, f"approval_status must be one of {sorted(APPROVAL_STATUSES)}")
        if payload.approval_status == "approved":
            db.add(Approval(entity_type="prop", entity_id=str(prop_id), decision="approved"))
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(prop, field, value)
    db.commit()
    db.refresh(prop)
    return row_to_dict(prop)


@router.delete("/props/{prop_id}", status_code=204)
def delete_prop(prop_id: int, db: Session = Depends(get_db)):
    from ..models import SceneProp

    prop = db.get(Prop, prop_id)
    if prop is None:
        raise HTTPException(404, "Prop not found")
    used = db.scalar(select(func.count(SceneProp.prop_id)).where(SceneProp.prop_id == prop_id)) or 0
    if used:
        raise HTTPException(409, f"Prop is used by {used} scene(s) — archive instead")
    db.delete(prop)
    db.commit()
    return None
