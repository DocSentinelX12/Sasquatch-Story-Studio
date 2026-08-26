"""Phase 10 Milestone F: read-only production planner API.

Every endpoint delegates to studio/services/planner.py — the single source of
planning truth. Nothing here creates jobs, queues generation, approves
content, changes statuses, or bypasses any gate.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..services import planner
from .deps import get_db

router = APIRouter(prefix="/api/production", tags=["production-planner"])


def _validate_episode_ids(db: Session, raw: Optional[str]) -> Optional[list[int]]:
    """Parse '1,2,3' into validated episode id ints; reject garbage cleanly."""
    if raw is None or raw.strip() == "":
        return None
    ids: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            value = int(token)
        except ValueError as error:
            raise HTTPException(422, f"episode_ids must be comma-separated integers, got {token!r}") from error
        if value < 1:
            raise HTTPException(422, f"episode_ids must be positive, got {value}")
        ids.append(value)
    if not ids:
        return None
    from ..models import Episode
    from sqlalchemy import select
    existing = set(db.scalars(select(Episode.id).where(Episode.id.in_(ids))).all())
    unknown = [i for i in ids if i not in existing]
    if unknown:
        raise HTTPException(422, f"Unknown episode id(s): {unknown}")
    return ids


@router.get("/overview")
def production_overview_endpoint(db: Session = Depends(get_db)):
    """Milestone A stats — real counts only."""
    return planner.production_overview(db)


@router.get("/recommendations")
def production_recommendations_endpoint(db: Session = Depends(get_db)):
    """Milestone B next actions — prioritized, deduplicated, linked."""
    return {"recommendations": planner.next_action_recommendations(db)}


@router.get("/plan")
def production_plan_endpoint(
    episode_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    """Milestone C plan — per-shot classification through real gates."""
    if episode_id is not None:
        from ..models import Episode
        if db.get(Episode, episode_id) is None:
            raise HTTPException(422, f"Unknown episode id {episode_id}")
    return planner.production_plan(db, episode_id=episode_id)


@router.get("/batch-plan")
def batch_plan_endpoint(
    episode_ids: Optional[str] = Query(default=None, description="comma-separated episode ids"),
    include_failed: bool = True,
    include_new_versions: bool = False,
    max_queue_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Milestone D batch plan — read-only queue plan."""
    ids = _validate_episode_ids(db, episode_ids)
    return planner.batch_production_plan(
        db, episode_ids=ids, include_failed=include_failed,
        include_new_versions=include_new_versions, max_queue_size=max_queue_size)


@router.get("/smart-plan")
def smart_plan_endpoint(
    episode_ids: Optional[str] = Query(default=None, description="comma-separated episode ids"),
    include_failed: bool = True,
    include_new_versions: bool = False,
    max_queue_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Milestone E smart plan — what to generate next, production-aware order."""
    ids = _validate_episode_ids(db, episode_ids)
    return planner.smart_generation_plan(
        db, episode_ids=ids, max_queue_size=max_queue_size,
        include_failed=include_failed, include_new_versions=include_new_versions)


@router.get("/character-consistency")
def character_consistency_endpoint(
    character_id: Optional[int] = Query(default=None, ge=1),
    episode_id: Optional[int] = Query(default=None, ge=1),
    scene_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    """Milestone G: read-only character consistency report."""
    try:
        return planner.character_consistency_report(
            db, character_id=character_id, episode_id=episode_id, scene_id=scene_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
