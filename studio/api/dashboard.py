"""Dashboard aggregate endpoint — real counts only, honest empty states."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Asset, Character, Episode, GenerationJob, Location, Project, Scene, Shot
from ..providers.registry import provider_status_list
from .deps import get_db, row_to_dict

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).order_by(Project.id)).all()
    episodes = db.scalars(select(Episode).order_by(Episode.id)).all()
    recent_assets = db.scalars(select(Asset).order_by(Asset.id.desc()).limit(8)).all()
    recent_jobs = db.scalars(select(GenerationJob).order_by(GenerationJob.id.desc()).limit(8)).all()

    episode_status_counts = dict(
        db.execute(select(Episode.status, func.count(Episode.id)).group_by(Episode.status)).all()
    )
    job_status_counts = dict(
        db.execute(select(GenerationJob.status, func.count(GenerationJob.id)).group_by(GenerationJob.status)).all()
    )
    asset_category_counts = dict(
        db.execute(select(Asset.category, func.count(Asset.id)).group_by(Asset.category)).all()
    )

    scene_total = db.scalar(select(func.count(Scene.id))) or 0
    shot_total = db.scalar(select(func.count(Shot.id))) or 0
    approved_assets = db.scalar(
        select(func.count(Asset.id)).where(Asset.status == "approved")
    ) or 0
    failed_jobs = db.scalar(
        select(func.count(GenerationJob.id)).where(GenerationJob.status == "failed")
    ) or 0

    return {
        "projects": [
            {
                **row_to_dict(p),
                "episode_count": db.scalar(
                    select(func.count(Episode.id)).where(Episode.project_id == p.id)
                ) or 0,
            }
            for p in projects
        ],
        "episodes_in_progress": [
            row_to_dict(e)
            for e in episodes
            if e.status not in ("exported", "released")
        ],
        "recent_assets": [row_to_dict(a) for a in recent_assets],
        "recent_jobs": [row_to_dict(j) for j in recent_jobs],
        "queue": {
            "counts_by_status": job_status_counts,
            "failed": failed_jobs,
            "total": db.scalar(select(func.count(GenerationJob.id))) or 0,
        },
        "production_stats": {
            "projects": len(projects),
            "episodes": len(episodes),
            "characters": db.scalar(select(func.count(Character.id))) or 0,
            "locations": db.scalar(select(func.count(Location.id))) or 0,
            "scenes": scene_total,
            "shots": shot_total,
            "assets": db.scalar(select(func.count(Asset.id))) or 0,
            "approved_assets": approved_assets,
            "episode_status_counts": episode_status_counts,
            "asset_category_counts": asset_category_counts,
        },
        "providers": provider_status_list(),
    }
