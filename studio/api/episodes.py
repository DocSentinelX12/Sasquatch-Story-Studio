"""Episode, scene and shot read endpoints (builders arrive in Phase 2)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..models import Act, Episode, Scene, Season, Shot
from .deps import get_db, row_to_dict, slugify

router = APIRouter(prefix="/api", tags=["episodes"])

VALID_EPISODE_STATUSES = {
    "planned", "outline", "script", "storyboard", "shot_building",
    "generating", "editing", "qc", "exported", "released",
}


class EpisodeCreate(BaseModel):
    project_id: int
    number: Optional[int] = None
    title: str = Field(min_length=1, max_length=160)
    slug: Optional[str] = None
    season_number: Optional[int] = None
    status: str = "planned"
    logline: Optional[str] = None
    premise: Optional[str] = None
    target_length_minutes: float = 8.0


class EpisodeUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    status: Optional[str] = None
    logline: Optional[str] = None
    premise: Optional[str] = None
    target_length_minutes: Optional[float] = None


def _next_episode_number(db: Session, project_id: int) -> int:
    current = db.scalar(
        select(func.max(Episode.number)).where(Episode.project_id == project_id)
    )
    return (current or 0) + 1


@router.get("/episodes")
def list_episodes(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = select(Episode).order_by(Episode.project_id, Episode.number)
    if project_id is not None:
        query = query.where(Episode.project_id == project_id)
    episodes = db.scalars(query).all()
    result = []
    for episode in episodes:
        scene_count = db.scalar(
            select(func.count(Scene.id)).where(Scene.episode_id == episode.id)
        ) or 0
        shot_count = db.scalar(
            select(func.count(Shot.id)).join(Scene, Shot.scene_id == Scene.id).where(Scene.episode_id == episode.id)
        ) or 0
        result.append({**row_to_dict(episode), "scene_count": scene_count, "shot_count": shot_count})
    return {"episodes": result}


@router.post("/episodes", status_code=201)
def create_episode(payload: EpisodeCreate, db: Session = Depends(get_db)):
    if payload.status not in VALID_EPISODE_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(VALID_EPISODE_STATUSES)}")
    season_id = None
    if payload.season_number is not None:
        season = db.scalar(
            select(Season).where(
                Season.project_id == payload.project_id, Season.number == payload.season_number
            )
        )
        if season is None:
            season = Season(project_id=payload.project_id, number=payload.season_number,
                            title=f"Season {payload.season_number}", status="planned")
            db.add(season)
            db.flush()
        season_id = season.id
    number = payload.number or _next_episode_number(db, payload.project_id)
    if db.scalar(select(Episode).where(Episode.project_id == payload.project_id, Episode.number == number)):
        raise HTTPException(409, f"Episode number {number} already exists in this project")
    episode = Episode(
        project_id=payload.project_id,
        season_id=season_id,
        number=number,
        title=payload.title,
        slug=payload.slug or slugify(payload.title),
        status=payload.status,
        logline=payload.logline,
        premise=payload.premise,
        target_length_minutes=payload.target_length_minutes,
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
        select(Scene).where(Scene.episode_id == episode_id).options(joinedload(Scene.location)).order_by(Scene.order_index)
    ).all()
    scene_payload = []
    for scene in scenes:
        shots = db.scalars(
            select(Shot).where(Shot.scene_id == scene.id).order_by(Shot.order_index)
        ).all()
        location_name = scene.location.name if scene.location else None
        scene_payload.append({
            **row_to_dict(scene),
            "location_name": location_name,
            "shots": [row_to_dict(s) for s in shots],
        })
    return {
        **row_to_dict(episode),
        "acts": [row_to_dict(a) for a in acts],
        "scenes": scene_payload,
    }


@router.patch("/episodes/{episode_id}")
def update_episode(episode_id: int, payload: EpisodeUpdate, db: Session = Depends(get_db)):
    episode = db.get(Episode, episode_id)
    if episode is None:
        raise HTTPException(404, "Episode not found")
    if payload.status is not None and payload.status not in VALID_EPISODE_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(VALID_EPISODE_STATUSES)}")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(episode, field, value)
    db.commit()
    db.refresh(episode)
    return row_to_dict(episode)
