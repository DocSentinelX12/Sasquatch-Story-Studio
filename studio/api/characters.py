"""Character Bible API: profiles, references, relationships, continuity."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..models import (
    Approval,
    Asset,
    Character,
    CharacterBible,
    CharacterReference,
    CharacterRelationship,
    REFERENCE_PURPOSES,
    REFERENCE_STATUSES,
)
from ..services.scanner import import_character_references, register_repo_assets
from .deps import get_db, row_to_dict

router = APIRouter(prefix="/api/characters", tags=["characters"])

LIFE_STATUSES = {"draft", "active", "archived"}
RELATIONSHIP_KINDS = {"friend", "family", "enemy", "companion", "neighbor", "recurring", "mentor", "other"}


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class CharacterCreate(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=120)
    role: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    species: Optional[str] = Field(default=None, max_length=120)
    character_kind: str = "person"
    age_group: Optional[str] = None
    char_ref: Optional[str] = None


class CharacterUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    role: Optional[str] = None
    description: Optional[str] = None
    species: Optional[str] = None
    family_ref: Optional[str] = None
    character_kind: Optional[str] = None
    age_group: Optional[str] = None
    approximate_age: Optional[str] = None
    personality_summary: Optional[str] = None
    appearance_summary: Optional[str] = None
    clothing: Optional[str] = None
    colors: Optional[list[str]] = None
    height_proportions: Optional[str] = None
    voice_notes: Optional[str] = None
    standard_appearance: Optional[str] = None
    current_outfit: Optional[str] = None
    standard_props: Optional[list[str]] = None
    personality_rules: Optional[list[str]] = None
    visual_rules: Optional[list[str]] = None
    never_changes: Optional[list[str]] = None
    master_visual_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None


class LifeStatusUpdate(BaseModel):
    status: str = Field(pattern="^(draft|active|archived)$")


class CharacterApproval(BaseModel):
    decision: str = Field(pattern="^(approved|rejected|changes_requested)$")
    note: Optional[str] = None


class RelationshipCreate(BaseModel):
    related_character_id: int
    kind: str = Field(pattern="^(friend|family|enemy|companion|neighbor|recurring|mentor|other)$")
    notes: Optional[str] = None


class ReferenceCreate(BaseModel):
    asset_id: int
    purpose: str = "primary"
    label: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None


class ReferenceUpdate(BaseModel):
    purpose: Optional[str] = None
    label: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    is_primary: Optional[bool] = None


class ReferenceApproval(BaseModel):
    decision: str = Field(pattern="^(approved|rejected|changes_requested)$")
    note: Optional[str] = None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _reference_payload(link: CharacterReference) -> dict:
    return {
        **row_to_dict(link),
        "asset": row_to_dict(link.asset) if link.asset else None,
    }


def _relationship_payload(rel: CharacterRelationship, name_map: dict[int, str]) -> dict:
    return {
        **row_to_dict(rel),
        "related_name": name_map.get(rel.related_character_id),
    }


def _get_character_or_404(db: Session, character_id: int) -> Character:
    character = db.get(Character, character_id)
    if character is None:
        raise HTTPException(404, "Character not found")
    return character


# --------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------

@router.get("")
def list_characters(
    project_id: Optional[int] = None,
    q: Optional[str] = None,
    life_status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if life_status is not None and life_status not in LIFE_STATUSES:
        raise HTTPException(422, f"life_status must be one of {sorted(LIFE_STATUSES)}")
    query = select(Character).order_by(Character.project_id, Character.name)
    if project_id is not None:
        query = query.where(Character.project_id == project_id)
    if life_status:
        query = query.where(Character.life_status == life_status)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(
            func.lower(Character.name).like(like),
            func.lower(Character.role).like(like),
            func.lower(Character.description).like(like),
            func.lower(Character.char_ref).like(like),
        ))
    characters = db.scalars(query).all()
    result = []
    for character in characters:
        total = db.scalar(
            select(func.count(CharacterReference.id)).where(
                CharacterReference.character_id == character.id
            )
        ) or 0
        approved = db.scalar(
            select(func.count(CharacterReference.id)).where(
                CharacterReference.character_id == character.id,
                CharacterReference.approval_status == "approved",
            )
        ) or 0
        result.append({
            **row_to_dict(character),
            "reference_count": total,
            "approved_reference_count": approved,
        })
    return {"characters": result}


@router.post("", status_code=201)
def create_character(payload: CharacterCreate, db: Session = Depends(get_db)):
    if payload.character_kind not in ("person", "animal"):
        raise HTTPException(422, "character_kind must be person | animal")
    character = Character(
        project_id=payload.project_id,
        name=payload.name,
        role=payload.role,
        description=payload.description,
        species=payload.species,
        character_kind=payload.character_kind,
        age_group=payload.age_group,
        char_ref=payload.char_ref,
        life_status="draft",
        approval_status="registered",
    )
    db.add(character)
    db.commit()
    db.refresh(character)
    return row_to_dict(character)


@router.get("/{character_id}")
def get_character(character_id: int, db: Session = Depends(get_db)):
    character = _get_character_or_404(db, character_id)
    bible = db.scalar(select(CharacterBible).where(CharacterBible.character_id == character_id))
    references = db.scalars(
        select(CharacterReference)
        .where(CharacterReference.character_id == character_id)
        .options(joinedload(CharacterReference.asset))
        .order_by(CharacterReference.is_primary.desc(), CharacterReference.id)
    ).all()

    # relationships (both directions) with names
    siblings = db.scalars(select(Character).where(Character.project_id == character.project_id)).all()
    name_map = {c.id: c.name for c in siblings}
    outgoing = db.scalars(
        select(CharacterRelationship).where(CharacterRelationship.character_id == character_id)
    ).all()
    incoming = db.scalars(
        select(CharacterRelationship).where(CharacterRelationship.related_character_id == character_id)
    ).all()

    return {
        **row_to_dict(character),
        "bible": row_to_dict(bible) if bible else None,
        "references": [_reference_payload(r) for r in references],
        "relationships": {
            "outgoing": [_relationship_payload(r, name_map) for r in outgoing],
            "incoming": [
                {**row_to_dict(r), "from_name": name_map.get(r.character_id)}
                for r in incoming
            ],
        },
        "siblings": [
            {"id": c.id, "name": c.name, "char_ref": c.char_ref}
            for c in siblings if c.id != character_id
        ],
    }


@router.patch("/{character_id}")
def update_character(character_id: int, payload: CharacterUpdate, db: Session = Depends(get_db)):
    character = _get_character_or_404(db, character_id)
    if payload.character_kind is not None and payload.character_kind not in ("person", "animal"):
        raise HTTPException(422, "character_kind must be person | animal")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(character, field, value)
    db.commit()
    db.refresh(character)
    return row_to_dict(character)


@router.post("/{character_id}/life")
def set_life_status(character_id: int, payload: LifeStatusUpdate, db: Session = Depends(get_db)):
    """Draft / Active / Archived lifecycle. Archiving never touches source assets."""
    character = _get_character_or_404(db, character_id)
    character.life_status = payload.status
    db.commit()
    db.refresh(character)
    return {
        **row_to_dict(character),
        "note": "Source assets are never deleted when a character is archived."
        if payload.status == "archived" else None,
    }


@router.post("/{character_id}/approval")
def set_character_approval(character_id: int, payload: CharacterApproval, db: Session = Depends(get_db)):
    character = _get_character_or_404(db, character_id)
    db.add(Approval(
        entity_type="character",
        entity_id=str(character_id),
        decision=payload.decision,
        note=payload.note,
    ))
    if payload.decision == "approved":
        character.approval_status = "approved"
    elif payload.decision in ("rejected", "changes_requested"):
        character.approval_status = "pending_approval"
    db.commit()
    db.refresh(character)
    return row_to_dict(character)


# --------------------------------------------------------------------------
# Relationships
# --------------------------------------------------------------------------

@router.post("/{character_id}/relationships", status_code=201)
def add_relationship(character_id: int, payload: RelationshipCreate, db: Session = Depends(get_db)):
    character = _get_character_or_404(db, character_id)
    if payload.related_character_id == character_id:
        raise HTTPException(422, "A character cannot have a relationship with itself")
    related = db.get(Character, payload.related_character_id)
    if related is None:
        raise HTTPException(404, "Related character not found")
    if related.project_id != character.project_id:
        raise HTTPException(422, "Characters must belong to the same project")
    existing = db.scalar(
        select(CharacterRelationship).where(
            CharacterRelationship.character_id == character_id,
            CharacterRelationship.related_character_id == payload.related_character_id,
            CharacterRelationship.kind == payload.kind,
        )
    )
    if existing:
        raise HTTPException(409, "That relationship already exists")
    relation = CharacterRelationship(
        character_id=character_id,
        related_character_id=payload.related_character_id,
        kind=payload.kind,
        notes=payload.notes,
    )
    db.add(relation)
    db.commit()
    db.refresh(relation)
    return {**row_to_dict(relation), "related_name": related.name}


@router.delete("/{character_id}/relationships/{relationship_id}", status_code=204)
def delete_relationship(character_id: int, relationship_id: int, db: Session = Depends(get_db)):
    relation = db.scalar(
        select(CharacterRelationship).where(
            CharacterRelationship.id == relationship_id,
            CharacterRelationship.character_id == character_id,
        )
    )
    if relation is None:
        raise HTTPException(404, "Relationship not found")
    db.delete(relation)
    db.commit()
    return None


# --------------------------------------------------------------------------
# References
# --------------------------------------------------------------------------

@router.post("/{character_id}/references", status_code=201)
def add_reference(character_id: int, payload: ReferenceCreate, db: Session = Depends(get_db)):
    character = _get_character_or_404(db, character_id)
    if payload.purpose not in REFERENCE_PURPOSES:
        raise HTTPException(422, f"purpose must be one of {sorted(REFERENCE_PURPOSES)}")
    asset = db.get(Asset, payload.asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    existing = db.scalar(
        select(CharacterReference).where(
            CharacterReference.character_id == character_id,
            CharacterReference.asset_id == payload.asset_id,
        )
    )
    if existing:
        raise HTTPException(409, "That asset is already linked to this character")
    link = CharacterReference(
        character_id=character_id,
        asset_id=payload.asset_id,
        purpose=payload.purpose,
        label=payload.label or asset.title,
        description=payload.description,
        tags=payload.tags or [],
        notes=payload.notes,
        is_primary=payload.purpose == "primary",
        approval_status="registered",  # never auto-approved
    )
    # Keep the asset linked to the character for library filters too.
    if asset.character_id is None:
        asset.character_id = character_id
    db.add(link)
    db.commit()
    db.refresh(link)
    return _reference_payload(link)


@router.patch("/{character_id}/references/{reference_id}")
def update_reference(character_id: int, reference_id: int, payload: ReferenceUpdate, db: Session = Depends(get_db)):
    link = db.scalar(
        select(CharacterReference).where(
            CharacterReference.id == reference_id,
            CharacterReference.character_id == character_id,
        )
    )
    if link is None:
        raise HTTPException(404, "Reference not found")
    if payload.purpose is not None and payload.purpose not in REFERENCE_PURPOSES:
        raise HTTPException(422, f"purpose must be one of {sorted(REFERENCE_PURPOSES)}")
    updates = payload.model_dump(exclude_none=True)
    if updates.get("is_primary") is True:
        # Only one primary reference per character.
        for other in db.scalars(
            select(CharacterReference).where(
                CharacterReference.character_id == character_id,
                CharacterReference.id != reference_id,
            )
        ).all():
            other.is_primary = False
    for field, value in updates.items():
        setattr(link, field, value)
    db.commit()
    db.refresh(link)
    return _reference_payload(link)


@router.delete("/{character_id}/references/{reference_id}", status_code=204)
def remove_reference(character_id: int, reference_id: int, db: Session = Depends(get_db)):
    """Unlink a reference. The asset itself is never deleted."""
    link = db.scalar(
        select(CharacterReference).where(
            CharacterReference.id == reference_id,
            CharacterReference.character_id == character_id,
        )
    )
    if link is None:
        raise HTTPException(404, "Reference not found")
    db.delete(link)
    db.commit()
    return None


@router.post("/{character_id}/references/{reference_id}/approval")
def review_reference(character_id: int, reference_id: int, payload: ReferenceApproval, db: Session = Depends(get_db)):
    link = db.scalar(
        select(CharacterReference).where(
            CharacterReference.id == reference_id,
            CharacterReference.character_id == character_id,
        )
    )
    if link is None:
        raise HTTPException(404, "Reference not found")
    db.add(Approval(
        entity_type="character_reference",
        entity_id=str(reference_id),
        decision=payload.decision,
        note=payload.note,
    ))
    link.approval_status = (
        "approved" if payload.decision == "approved" else
        "rejected" if payload.decision == "rejected" else "pending_approval"
    )
    if payload.decision == "approved" and link.asset is not None:
        # Approving a production reference promotes the asset itself as well.
        link.asset.status = "approved"
        db.add(Approval(
            entity_type="asset",
            entity_id=str(link.asset.id),
            decision="approved",
            note=f"Approved as {link.purpose} reference for {link.character.name if link.character else 'character'}",
        ))
    db.commit()
    db.refresh(link)
    return _reference_payload(link)


# --------------------------------------------------------------------------
# Repository import (Phase 1 scanner, honest reporting)
# --------------------------------------------------------------------------

@router.post("/import")
def import_from_repo(project_id: int, db: Session = Depends(get_db)):
    """Scan the repository for creator character artwork and link references.

    Never modifies files on disk — registration only. Registered assets are
    NOT approved for generation until approved explicitly.
    """
    scan = register_repo_assets(db, project_id=project_id)
    links = import_character_references(db, project_id)
    family_folders = []
    for path in scan.registered_paths:
        parts = path.split("/")
        if len(parts) >= 4 and parts[0] == "assets" and parts[1] == "characters" and parts[2] == "source":
            folder = parts[3]
            if folder.endswith("-family") or folder.startswith("family-"):
                family_folders.append(folder)
    return {
        "scan": scan.as_dict(),
        "links": links,
        "family_intake_folders": sorted(set(family_folders)),
        "note": (
            "Registration only — nothing on disk was modified. Registered assets "
            "are NOT approved for generation until you approve them explicitly."
        ),
    }
