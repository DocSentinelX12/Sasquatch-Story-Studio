"""Project / season management endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Asset, Character, Episode, Location, Project, Scene, Season, Shot
from .deps import get_db, row_to_dict, slugify

router = APIRouter(prefix="/api/projects", tags=["projects"])

VALID_PROJECT_STATUSES = {"planning", "active", "paused", "archived"}


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    series_premise: str = ""
    status: str = "active"
    current_season_number: int = 1


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    series_premise: Optional[str] = None
    status: Optional[str] = None
    current_season_number: Optional[int] = None


def _project_counts(db: Session, project_id: int) -> dict:
    episode_count = db.scalar(select(func.count(Episode.id)).where(Episode.project_id == project_id)) or 0
    character_count = db.scalar(select(func.count(Character.id)).where(Character.project_id == project_id)) or 0
    location_count = db.scalar(select(func.count(Location.id)).where(Location.project_id == project_id)) or 0
    asset_count = db.scalar(select(func.count(Asset.id)).where(Asset.project_id == project_id)) or 0
    scene_count = (
        db.scalar(
            select(func.count(Scene.id))
            .join(Episode, Scene.episode_id == Episode.id)
            .where(Episode.project_id == project_id)
        )
        or 0
    )
    shot_count = (
        db.scalar(
            select(func.count(Shot.id))
            .join(Scene, Shot.scene_id == Scene.id)
            .join(Episode, Scene.episode_id == Episode.id)
            .where(Episode.project_id == project_id)
        )
        or 0
    )
    return {
        "episodes": episode_count,
        "characters": character_count,
        "locations": location_count,
        "assets": asset_count,
        "scenes": scene_count,
        "shots": shot_count,
    }


@router.get("")
def list_projects(db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).order_by(Project.id)).all()
    return {
        "projects": [
            {**row_to_dict(p), "counts": _project_counts(db, p.id)} for p in projects
        ]
    }


@router.post("", status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    if payload.status not in VALID_PROJECT_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(VALID_PROJECT_STATUSES)}")
    slug = slugify(payload.name)
    if db.scalar(select(Project).where((Project.slug == slug) | (Project.name == payload.name))):
        raise HTTPException(409, "A project with that name already exists")
    project = Project(
        name=payload.name,
        slug=slug,
        description=payload.description,
        series_premise=payload.series_premise,
        status=payload.status,
        current_season_number=payload.current_season_number,
    )
    db.add(project)
    db.flush()
    season = Season(project_id=project.id, number=1, title="Season 1", status="planned")
    db.add(season)
    db.commit()
    db.refresh(project)
    return {**row_to_dict(project), "counts": _project_counts(db, project.id)}


@router.get("/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    seasons = db.scalars(
        select(Season).where(Season.project_id == project_id).order_by(Season.number)
    ).all()
    episodes = db.scalars(
        select(Episode).where(Episode.project_id == project_id).order_by(Episode.number)
    ).all()
    return {
        **row_to_dict(project),
        "counts": _project_counts(db, project_id),
        "seasons": [row_to_dict(s) for s in seasons],
        "episodes": [row_to_dict(e) for e in episodes],
    }


@router.patch("/{project_id}")
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if payload.status is not None and payload.status not in VALID_PROJECT_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(VALID_PROJECT_STATUSES)}")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return {**row_to_dict(project), "counts": _project_counts(db, project_id)}
