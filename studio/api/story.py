"""Story layer API: Story Bible, canon entries, story ideas/development,
AI-assistance hooks (honest), and global search."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Approval,
    CanonEntry,
    Character,
    Episode,
    Location,
    Prop,
    Scene,
    Story,
    StoryBible,
)
from ..providers.registry import AdapterNotImplemented, ProviderNotConfigured
from ..services.story_assist import ASSIST_TASKS, AssistRequest, run_assist, story_providers
from .deps import get_db, row_to_dict

router = APIRouter(prefix="/api", tags=["story"])

BIBLE_STATUSES = {"draft", "approved", "archived"}


# --------------------------------------------------------------------------
# Story Bible (PART 1)
# --------------------------------------------------------------------------

class BibleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[dict] = None
    status: Optional[str] = None
    edit_approved: bool = False   # required to modify an approved bible


@router.get("/story-bible")
def get_bible(project_id: int, db: Session = Depends(get_db)):
    bible = db.scalar(select(StoryBible).where(StoryBible.project_id == project_id))
    if bible is None:
        return {"story_bible": None}
    return {"story_bible": row_to_dict(bible)}


@router.patch("/story-bible/{bible_id}")
def update_bible(bible_id: int, payload: BibleUpdate, db: Session = Depends(get_db)):
    bible = db.get(StoryBible, bible_id)
    if bible is None:
        raise HTTPException(404, "Story Bible not found")
    if payload.status is not None and payload.status not in BIBLE_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(BIBLE_STATUSES)}")
    protected = bible.status == "approved" and not payload.edit_approved
    changing_content = payload.content is not None and payload.content != bible.content
    if protected and (changing_content or payload.title is not None):
        raise HTTPException(
            409,
            "This Story Bible is approved canon. Pass edit_approved=true to edit it; "
            "the change is recorded in the approval ledger and bumps the version.",
        )
    if payload.title is not None:
        bible.title = payload.title
    if changing_content:
        bible.content = payload.content
        bible.version = (bible.version or 1) + 1
    if payload.status is not None:
        bible.status = payload.status
    db.add(Approval(
        entity_type="story_bible", entity_id=str(bible_id),
        decision="approved" if payload.edit_approved else "changes_requested",
        note="edited approved canon" if payload.edit_approved else "story bible edit",
    ))
    db.commit()
    db.refresh(bible)
    return row_to_dict(bible)


# --------------------------------------------------------------------------
# Canon system (PART 2)
# --------------------------------------------------------------------------

class CanonCreate(BaseModel):
    project_id: int
    category: str
    title: str = Field(min_length=1, max_length=200)
    statement: str = ""
    details: Optional[dict] = None
    status: str = "draft"
    episode_id: Optional[int] = None


class CanonUpdate(BaseModel):
    title: Optional[str] = None
    statement: Optional[str] = None
    details: Optional[dict] = None
    status: Optional[str] = None


@router.get("/canon")
def list_canon(
    project_id: int,
    category: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    from ..models.story import CANON_CATEGORIES, CANON_STATUSES

    if category is not None and category not in CANON_CATEGORIES:
        raise HTTPException(422, f"category must be one of {sorted(CANON_CATEGORIES)}")
    if status is not None and status not in CANON_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(CANON_STATUSES)}")
    query = select(CanonEntry).where(CanonEntry.project_id == project_id)
    if category:
        query = query.where(CanonEntry.category == category)
    if status:
        query = query.where(CanonEntry.status == status)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(
            func.lower(CanonEntry.title).like(like),
            func.lower(CanonEntry.statement).like(like),
        ))
    entries = db.scalars(query.order_by(CanonEntry.category, CanonEntry.id)).all()
    counts = dict(db.execute(
        select(CanonEntry.status, func.count(CanonEntry.id))
        .where(CanonEntry.project_id == project_id).group_by(CanonEntry.status)
    ).all())
    return {"canon": [row_to_dict(e) for e in entries], "counts_by_status": counts}


@router.post("/canon", status_code=201)
def create_canon(payload: CanonCreate, db: Session = Depends(get_db)):
    from ..models.story import CANON_CATEGORIES, CANON_STATUSES

    if payload.category not in CANON_CATEGORIES:
        raise HTTPException(422, f"category must be one of {sorted(CANON_CATEGORIES)}")
    if payload.status not in CANON_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(CANON_STATUSES)}")
    if payload.status == "canon" and not payload.statement:
        raise HTTPException(422, "Canon entries need a statement")
    entry = CanonEntry(
        project_id=payload.project_id, category=payload.category,
        title=payload.title, statement=payload.statement,
        details=payload.details, status=payload.status,
        origin="manual", episode_id=payload.episode_id,
    )
    db.add(entry)
    if payload.status == "canon":
        db.add(Approval(entity_type="canon", entity_id="new", decision="approved",
                        note=f"{payload.category}: {payload.title}"))
    db.commit()
    db.refresh(entry)
    return row_to_dict(entry)


@router.patch("/canon/{entry_id}")
def update_canon(entry_id: int, payload: CanonUpdate, db: Session = Depends(get_db)):
    from ..models.story import CANON_STATUSES

    entry = db.get(CanonEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "Canon entry not found")
    if payload.status is not None and payload.status not in CANON_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(CANON_STATUSES)}")
    # canon entries can only be created as canon via explicit approval flow
    if payload.status == "canon" and entry.status != "canon":
        raise HTTPException(409, "Use POST /canon/{id}/approve to make an entry canon")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return row_to_dict(entry)


@router.post("/canon/{entry_id}/approve")
def approve_canon(entry_id: int, note: Optional[str] = None, db: Session = Depends(get_db)):
    """Proposed/draft → canon. The only path to canon status."""
    entry = db.get(CanonEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "Canon entry not found")
    if entry.status == "deprecated":
        raise HTTPException(409, "Deprecated entries must be re-proposed first")
    if entry.status != "canon":
        entry.status = "canon"
        db.add(Approval(entity_type="canon", entity_id=str(entry_id),
                        decision="approved", note=note))
        db.commit()
    db.refresh(entry)
    return row_to_dict(entry)


@router.post("/canon/{entry_id}/propose")
def propose_canon(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(CanonEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "Canon entry not found")
    if entry.status == "canon":
        raise HTTPException(409, "Entry is already canon")
    entry.status = "proposed"
    db.commit()
    db.refresh(entry)
    return row_to_dict(entry)


@router.post("/canon/{entry_id}/deprecate")
def deprecate_canon(entry_id: int, note: Optional[str] = None, db: Session = Depends(get_db)):
    entry = db.get(CanonEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "Canon entry not found")
    entry.status = "deprecated"
    db.add(Approval(entity_type="canon", entity_id=str(entry_id),
                    decision="changes_requested", note=note or "deprecated"))
    db.commit()
    db.refresh(entry)
    return row_to_dict(entry)


@router.delete("/canon/{entry_id}", status_code=204)
def delete_canon(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(CanonEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "Canon entry not found")
    if entry.status == "canon":
        raise HTTPException(409, "Canon entries cannot be deleted — deprecate them instead")
    db.delete(entry)
    db.commit()
    return None


# --------------------------------------------------------------------------
# Stories (PART 3 + 4)
# --------------------------------------------------------------------------

class StoryCreate(BaseModel):
    project_id: int
    title: str = Field(min_length=1, max_length=200)
    idea_text: str = ""


class StoryUpdate(BaseModel):
    title: Optional[str] = None
    idea_text: Optional[str] = None
    logline: Optional[str] = None
    premise: Optional[str] = None
    main_conflict: Optional[str] = None
    stakes: Optional[str] = None
    setting: Optional[str] = None
    beginning: Optional[str] = None
    middle: Optional[str] = None
    ending: Optional[str] = None
    resolution: Optional[str] = None
    goal: Optional[str] = None
    obstacles: Optional[list] = None
    motivations: Optional[list] = None
    turning_points: Optional[list] = None
    climax: Optional[str] = None
    beats: Optional[dict] = None
    character_ids: Optional[list] = None
    status: Optional[str] = None


@router.get("/stories")
def list_stories(
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    from ..models.story import STORY_STATUSES

    if status is not None and status not in STORY_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(STORY_STATUSES)}")
    query = select(Story)
    if project_id:
        query = query.where(Story.project_id == project_id)
    if status:
        query = query.where(Story.status == status)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(
            func.lower(Story.title).like(like),
            func.lower(Story.idea_text).like(like),
            func.lower(Story.logline).like(like),
            func.lower(Story.premise).like(like),
        ))
    stories = db.scalars(query.order_by(Story.id.desc())).all()
    result = []
    for story in stories:
        characters = []
        for cid in (story.character_ids or []):
            character = db.get(Character, cid)
            if character:
                characters.append({"id": character.id, "name": character.name})
        result.append({**row_to_dict(story), "characters": characters})
    return {"stories": result}


@router.post("/stories", status_code=201)
def create_story(payload: StoryCreate, db: Session = Depends(get_db)):
    story = Story(project_id=payload.project_id, title=payload.title,
                  idea_text=payload.idea_text, status="draft")
    db.add(story)
    db.commit()
    db.refresh(story)
    return row_to_dict(story)


@router.get("/stories/{story_id}")
def get_story(story_id: int, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(404, "Story not found")
    characters = []
    for cid in (story.character_ids or []):
        character = db.get(Character, cid)
        if character:
            characters.append({
                "id": character.id, "name": character.name, "species": character.species,
                "personality_summary": character.personality_summary,
                "never_changes": character.never_changes,
            })
    bible = db.scalar(select(StoryBible).where(StoryBible.project_id == story.project_id))
    return {
        **row_to_dict(story),
        "characters": characters,
        "bible_id": bible.id if bible else None,
    }


@router.patch("/stories/{story_id}")
def update_story(story_id: int, payload: StoryUpdate, db: Session = Depends(get_db)):
    from ..models.story import STORY_STATUSES

    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(404, "Story not found")
    if payload.status is not None and payload.status not in STORY_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(STORY_STATUSES)}")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(story, field, value)
    if payload.status == "approved":
        db.add(Approval(entity_type="story", entity_id=str(story_id), decision="approved"))
    db.commit()
    db.refresh(story)
    return row_to_dict(story)


@router.delete("/stories/{story_id}", status_code=204)
def delete_story(story_id: int, db: Session = Depends(get_db)):
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(404, "Story not found")
    if story.status == "approved":
        raise HTTPException(409, "Approved stories cannot be deleted — archive instead")
    db.delete(story)
    db.commit()
    return None


@router.post("/stories/{story_id}/create-episode", status_code=201)
def create_episode_from_story(story_id: int, db: Session = Depends(get_db)):
    """Approved story → new episode draft (story stays attached)."""
    story = db.get(Story, story_id)
    if story is None:
        raise HTTPException(404, "Story not found")
    if story.status != "approved":
        raise HTTPException(409, "Only approved stories can become episodes")
    existing = db.scalar(select(Episode).where(Episode.story_id == story_id))
    if existing:
        raise HTTPException(409, f"Story already has episode #{existing.number}")
    number = (db.scalar(
        select(func.max(Episode.number)).where(Episode.project_id == story.project_id)
    ) or 0) + 1
    episode = Episode(
        project_id=story.project_id, number=number, title=story.title,
        slug=story.title.lower().replace(" ", "-")[:60],
        logline=story.logline, premise=story.premise, summary=story.idea_text,
        status="development", story_id=story.id,
    )
    db.add(episode)
    db.flush()
    for cid in (story.character_ids or []):
        pass  # characters are cast per-scene (Phase 3 scene builder)
    db.commit()
    db.refresh(episode)
    return row_to_dict(episode)


# --------------------------------------------------------------------------
# AI story assistance hooks (PART 16) — honest states only
# --------------------------------------------------------------------------

class AssistCall(BaseModel):
    task: str
    input_text: str = ""
    provider_key: Optional[str] = None
    context: Optional[dict] = None


@router.get("/story-assist/providers")
def assist_providers():
    return {"providers": story_providers(), "tasks": list(ASSIST_TASKS),
            "connected": False}  # honest: no text adapter exists in Phase 3


@router.post("/story-assist")
def assist(payload: AssistCall, db: Session = Depends(get_db)):
    if payload.task not in ASSIST_TASKS:
        raise HTTPException(422, f"task must be one of {sorted(ASSIST_TASKS)}")
    try:
        result = run_assist(AssistRequest(
            task=payload.task, input_text=payload.input_text,
            context=payload.context or {},
        ), payload.provider_key)
    except ProviderNotConfigured as error:
        raise HTTPException(409, {
            "error": "provider_not_configured", "message": str(error),
            "hint": "Manual writing always works — AI assistance is optional.",
        }) from error
    except AdapterNotImplemented as error:
        raise HTTPException(501, {
            "error": "adapter_not_implemented", "message": str(error),
        }) from error
    return {"task": result.task, "provider": result.provider, "output": result.output}


# --------------------------------------------------------------------------
# Global search (PART 18)
# --------------------------------------------------------------------------

@router.get("/search")
def global_search(q: str, project_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = (q or "").strip()
    if len(q) < 2:
        return {"q": q, "results": {}}
    like = f"%{q.lower()}%"

    def matcher(*columns):
        return or_(*[func.lower(c).like(like) for c in columns])

    results: dict[str, list] = {}

    def add(key, rows, formatter):
        results[key] = [formatter(r) for r in rows]

    stories = db.scalars(select(Story).where(matcher(Story.title, Story.idea_text, Story.logline)).limit(10)).all()
    add("stories", stories, lambda s: {"id": s.id, "title": s.title, "subtitle": (s.logline or s.idea_text or "")[:90], "href": f"#/stories/{s.id}"})
    episodes = db.scalars(select(Episode).where(matcher(Episode.title, Episode.logline, Episode.premise, Episode.summary)).limit(10)).all()
    add("episodes", episodes, lambda e: {"id": e.id, "title": f"EP-{e.number:03d} {e.title}", "subtitle": (e.logline or "")[:90], "href": f"#/episodes/{e.id}"})
    scenes = db.scalars(select(Scene).where(matcher(Scene.title, Scene.summary, Scene.visual_action)).limit(10)).all()
    add("scenes", scenes, lambda s: {"id": s.id, "title": s.scene_ref or f"Scene {s.number}", "subtitle": (s.title or "")[:90], "href": f"#/episodes/{s.episode_id}?scene={s.id}"})
    characters = db.scalars(select(Character).where(matcher(Character.name, Character.description, Character.role)).limit(10)).all()
    add("characters", characters, lambda c: {"id": c.id, "title": c.name, "subtitle": (c.role or "")[:90], "href": f"#/characters/{c.id}"})
    locations = db.scalars(select(Location).where(matcher(Location.name, Location.description)).limit(10)).all()
    add("locations", locations, lambda l: {"id": l.id, "title": l.name, "subtitle": (l.kind or "")[:90], "href": f"#/world?tab=locations"})
    props = db.scalars(select(Prop).where(matcher(Prop.name, Prop.description)).limit(10)).all()
    add("props", props, lambda p: {"id": p.id, "title": p.name, "subtitle": (p.description or "")[:90], "href": f"#/world?tab=props"})
    canon = db.scalars(select(CanonEntry).where(matcher(CanonEntry.title, CanonEntry.statement)).limit(10)).all()
    add("canon", canon, lambda c: {"id": c.id, "title": c.title, "subtitle": f"{c.category} · {c.status}", "href": f"#/story?tab=canon"})
    return {"q": q, "results": results}
