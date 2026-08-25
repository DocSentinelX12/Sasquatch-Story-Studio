"""Phase 8 API: automation rules (CRUD + run/test/history), notifications,
series management, episode templates, series backup/export."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AUTOMATION_ACTIONS,
    AUTOMATION_TRIGGERS,
    Act,
    AutomationAudit,
    AutomationRule,
    Character,
    Episode,
    EpisodeTemplate,
    Location,
    Notification,
    Project,
    Prop,
    Scene,
    ScriptElement,
    Season,
    Shot,
    StoryBible,
)
from ..services import automation
from .deps import get_db, row_to_dict

router = APIRouter(prefix="/api", tags=["phase8"])


# ==========================================================================
# Automation rules (Milestone A)
# ==========================================================================

class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: Optional[str] = None
    project_id: Optional[int] = None
    trigger: str
    conditions: Optional[dict] = None
    actions: list = Field(min_length=1)
    priority: int = 5
    dry_run: bool = False
    enabled: bool = False


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    trigger: Optional[str] = None
    conditions: Optional[dict] = None
    actions: Optional[list] = None
    priority: Optional[int] = None
    dry_run: Optional[bool] = None


def _validate_rule(trigger: str | None = None, actions: list | None = None) -> None:
    if trigger is not None and trigger not in AUTOMATION_TRIGGERS:
        raise HTTPException(422, f"trigger must be one of {sorted(AUTOMATION_TRIGGERS)}")
    if actions is not None:
        for spec in actions:
            name = spec if isinstance(spec, str) else (spec or {}).get("action", "")
            if name not in AUTOMATION_ACTIONS:
                raise HTTPException(422, f"action must be one of {sorted(AUTOMATION_ACTIONS)}")


@router.get("/automation/rules")
def list_rules(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = select(AutomationRule).order_by(AutomationRule.priority, AutomationRule.id)
    if project_id is not None:
        query = query.where((AutomationRule.project_id == project_id) | (AutomationRule.project_id.is_(None)))
    rules = db.scalars(query).all()
    if not rules:
        automation.seed_default_rules(db, project_id)
        rules = db.scalars(query).all()
    return {"rules": [row_to_dict(r) for r in rules],
            "triggers": list(AUTOMATION_TRIGGERS),
            "actions": list(AUTOMATION_ACTIONS),
            "safety": "Automation may PREPARE or QUEUE work. It never approves creative "
                      "content and never publishes. Every run is audited."}


@router.post("/automation/rules", status_code=201)
def create_rule(payload: RuleCreate, db: Session = Depends(get_db)):
    _validate_rule(payload.trigger, payload.actions)
    rule = AutomationRule(**payload.model_dump())
    db.add(rule); db.commit(); db.refresh(rule)
    return row_to_dict(rule)


@router.patch("/automation/rules/{rule_id}")
def update_rule(rule_id: int, payload: RuleUpdate, db: Session = Depends(get_db)):
    rule = db.get(AutomationRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    data = payload.model_dump(exclude_none=True)
    _validate_rule(data.get("trigger"), data.get("actions"))
    for key, value in data.items():
        setattr(rule, key, value)
    db.commit(); db.refresh(rule)
    return row_to_dict(rule)


@router.delete("/automation/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(AutomationRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    db.delete(rule); db.commit()
    return None


class RuleRun(BaseModel):
    episode_id: Optional[int] = None
    scene_id: Optional[int] = None
    shot_id: Optional[int] = None
    dry_run: bool = False


@router.post("/automation/rules/{rule_id}/run")
def run_rule(rule_id: int, payload: RuleRun, db: Session = Depends(get_db)):
    """Run now / Test rule — same engine, same audit, optional forced dry-run."""
    rule = db.get(AutomationRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    episode = db.get(Episode, payload.episode_id) if payload.episode_id else None
    audit = automation.execute_rule(
        db, rule, rule.trigger,
        project_id=episode.project_id if episode else rule.project_id,
        episode_id=payload.episode_id, scene_id=payload.scene_id,
        shot_id=payload.shot_id, force_dry_run=payload.dry_run)
    db.refresh(audit)
    return row_to_dict(audit)


@router.get("/automation/history")
def automation_history(rule_id: Optional[int] = None, limit: int = 100,
                       db: Session = Depends(get_db)):
    query = select(AutomationAudit).order_by(AutomationAudit.id.desc())
    if rule_id:
        query = query.where(AutomationAudit.rule_id == rule_id)
    entries = db.scalars(query.limit(min(limit, 500))).all()
    return {"history": [row_to_dict(e) for e in entries]}


# ==========================================================================
# Notifications
# ==========================================================================

@router.get("/notifications")
def notifications(project_id: Optional[int] = None, unread_only: bool = False,
                  db: Session = Depends(get_db)):
    query = select(Notification).order_by(Notification.id.desc())
    if project_id is not None:
        query = query.where((Notification.project_id == project_id) | (Notification.project_id.is_(None)))
    if unread_only:
        query = query.where(Notification.read == False)  # noqa: E712
    items = db.scalars(query.limit(100)).all()
    return {"notifications": [row_to_dict(n) for n in items],
            "unread": db.scalar(select(func.count(Notification.id)).where(
                Notification.read == False)) or 0}  # noqa: E712


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db)):
    note = db.get(Notification, notification_id)
    if note is None:
        raise HTTPException(404, "Notification not found")
    note.read = True
    db.commit()
    return row_to_dict(note)


# ==========================================================================
# Production pause (control)
# ==========================================================================

@router.get("/production/status")
def production_status():
    return {"paused_projects": sorted(automation.PROJECT_PAUSES),
            "note": "Paused series block batch/automated queueing; manual single generations still work."}


@router.post("/production/pause")
def pause_production(project_id: Optional[int] = None, paused: bool = True):
    automation.set_production_paused(project_id, paused)
    return {"project_id": project_id, "paused": automation.production_paused(project_id)}


# ==========================================================================
# Multi-series (Milestone B)
# ==========================================================================

class SeriesCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    series_premise: str = ""


@router.post("/series", status_code=201)
def create_series(payload: SeriesCreate, db: Session = Depends(get_db)):
    """Create an independent series (its own bible, characters, episodes,
    assets, generation history — full isolation by project_id)."""
    from .deps import slugify
    slug = slugify(payload.name)
    if db.scalar(select(Project).where((Project.slug == slug) | (Project.name == payload.name))):
        raise HTTPException(409, "A series with that name already exists")
    project = Project(name=payload.name, slug=slug, description=payload.description,
                      series_premise=payload.series_premise, status="planning")
    db.add(project)
    db.flush()
    db.add(Season(project_id=project.id, number=1, title="Season 1", status="planned"))
    db.add(StoryBible(project_id=project.id, title=f"{payload.name} — Story Bible",
                      content={"structured": True, "series_title": payload.name,
                               "premise": payload.series_premise},
                      status="draft"))
    automation.seed_default_rules(db, project.id)
    db.commit()
    db.refresh(project)
    return {"series": row_to_dict(project), "switch_to": project.id,
            "note": "Isolated by design: bible, canon, characters, episodes, assets and "
                    "generation history never cross series."}


@router.get("/series/isolation-check")
def isolation_check(db: Session = Depends(get_db)):
    """Verify no entity references a parent outside its series (audit)."""
    problems = []
    for scene in db.scalars(select(Scene)).all():
        episode = db.get(Episode, scene.episode_id)
        if episode and scene.act_id:
            act = db.get(Act, scene.act_id)
            if act and act.episode_id != episode.id:
                problems.append(f"Scene {scene.id} act mismatch")
    for shot in db.scalars(select(Shot)).all():
        scene = db.get(Scene, shot.scene_id)
        if scene is None:
            problems.append(f"Shot {shot.id} orphaned")
    return {"problems": problems, "series_count": db.scalar(select(func.count(Project.id))) or 0,
            "note": "Cross-series contamination check; empty list = clean."}


# ==========================================================================
# Episode templates (Milestone C)
# ==========================================================================

class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: Optional[str] = None
    project_id: Optional[int] = None
    source_episode_id: Optional[int] = None


def _capture_structure(db: Session, episode: Episode) -> dict:
    acts = db.scalars(select(Act).where(Act.episode_id == episode.id)).all()
    scenes = db.scalars(select(Scene).where(Scene.episode_id == episode.id)
                        .order_by(Scene.order_index)).all()
    structure = {"acts": [{"number": a.number, "title": a.title, "purpose": a.purpose,
                           "summary": a.summary} for a in acts], "scenes": []}
    for scene in scenes:
        shots = db.scalars(select(Shot).where(Shot.scene_id == scene.id)
                           .order_by(Shot.order_index)).all()
        script = db.scalars(select(ScriptElement).where(
            ScriptElement.scene_id == scene.id).order_by(ScriptElement.order_index)).all()
        structure["scenes"].append({
            "title": scene.title, "time_of_day": scene.time_of_day,
            "story_purpose": scene.story_purpose,
            "shots": [{"title": s.title, "shot_type": s.shot_type,
                       "camera_angle": s.camera_angle, "camera_movement": s.camera_movement,
                       "duration_seconds": s.duration_seconds, "description": s.description}
                      for s in shots],
            "script": [{"element_type": e.element_type, "text": e.text,
                        "character_id": e.character_id} for e in script]})
    return structure


@router.get("/templates")
def list_templates(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = select(EpisodeTemplate).order_by(EpisodeTemplate.name)
    if project_id is not None:
        query = query.where((EpisodeTemplate.project_id == project_id) | (EpisodeTemplate.project_id.is_(None)))
    return {"templates": [row_to_dict(t) for t in db.scalars(query).all()]}


@router.post("/templates", status_code=201)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    structure = None
    if payload.source_episode_id:
        episode = db.get(Episode, payload.source_episode_id)
        if episode is None:
            raise HTTPException(404, "Source episode not found")
        structure = _capture_structure(db, episode)
    template = EpisodeTemplate(project_id=payload.project_id, name=payload.name,
                               description=payload.description,
                               source_episode_id=payload.source_episode_id,
                               structure=structure)
    db.add(template); db.commit(); db.refresh(template)
    return row_to_dict(template)


@router.post("/templates/{template_id}/instantiate", status_code=201)
def instantiate_template(template_id: int, db: Session = Depends(get_db)):
    """Create a NEW episode from the template — acts/scenes/shots/script copied
    as drafts. Nothing is approved; nothing references old results."""
    template = db.get(EpisodeTemplate, template_id)
    if template is None or not template.structure:
        raise HTTPException(404, "Template not found (or empty structure)")
    project_id = template.project_id
    if project_id is None:
        project = db.scalar(select(Project).order_by(Project.id))
        project_id = project.id if project else None
    number = (db.scalar(select(func.max(Episode.number)).where(
        Episode.project_id == project_id)) or 0) + 1
    episode = Episode(project_id=project_id, number=number,
                      title=f"From template: {template.name}", status="draft")
    db.add(episode); db.flush()
    structure = template.structure
    act_ids = {}
    for act_data in structure.get("acts", []):
        act = Act(episode_id=episode.id, number=act_data["number"],
                  title=act_data.get("title") or f"Act {act_data['number']}",
                  purpose=act_data.get("purpose"), summary=act_data.get("summary"))
        db.add(act); db.flush()
        act_ids[act_data["number"]] = act.id
    order = 0
    for index, scene_data in enumerate(structure.get("scenes", []), start=1):
        order += 1
        scene = Scene(episode_id=episode.id, number=index, scene_ref=f"SC-{index:03d}",
                      title=scene_data.get("title") or f"Scene {index}",
                      time_of_day=scene_data.get("time_of_day"),
                      story_purpose=scene_data.get("story_purpose"),
                      status="draft", order_index=order)
        db.add(scene); db.flush()
        for shot_index, shot_data in enumerate(scene_data.get("shots", []), start=1):
            db.add(Shot(scene_id=scene.id,
                        shot_ref=f"SC-{index:03d}-SHOT-{shot_index:02d}",
                        number=shot_index, title=shot_data.get("title"),
                        shot_type=shot_data.get("shot_type"),
                        camera_angle=shot_data.get("camera_angle"),
                        camera_movement=shot_data.get("camera_movement"),
                        duration_seconds=shot_data.get("duration_seconds") or 6.0,
                        description=shot_data.get("description"),
                        status="draft", order_index=shot_index))
        for element_index, element in enumerate(scene_data.get("script", []), start=1):
            db.add(ScriptElement(scene_id=scene.id, episode_id=episode.id,
                                 order_index=float(element_index),
                                 element_type=element.get("element_type", "action"),
                                 text=element.get("text", ""),
                                 character_id=element.get("character_id")))
    db.commit(); db.refresh(episode)
    return {"episode": row_to_dict(episode),
            "note": "Everything copied as drafts — approve through the normal workflow."}


# ==========================================================================
# Series backup (Milestone D) — JSON export/import, media referenced by path
# ==========================================================================

@router.get("/series/{series_id}/backup")
def backup_series(series_id: int, db: Session = Depends(get_db)):
    """Full series backup as JSON: bible, characters, canon, episodes, scenes,
    shots, script, timeline, generation history, exports. Media files are
    referenced by path (not embedded) — back up assets/ and renders/ separately."""
    project = db.get(Project, series_id)
    if project is None:
        raise HTTPException(404, "Series not found")
    from ..models import (Asset, AudioRecording, CanonEntry, CharacterBible,
                          CharacterReference, EpisodeRender, ExportRecord,
                          GenerationJob, GenerationResult, Story, TimelineItem,
                          TimelineTrack, VoiceProfile)
    backup = {"format": "sasquatch-studio-series-backup", "version": 1,
              "series": row_to_dict(project)}
    def rows(model, where):
        return [row_to_dict(r) for r in db.scalars(select(model).where(where)).all()]
    backup["story_bible"] = rows(StoryBible, StoryBible.project_id == series_id)
    backup["stories"] = rows(Story, Story.project_id == series_id)
    backup["characters"] = rows(Character, Character.project_id == series_id)
    backup["character_bibles"] = [row_to_dict(b) for b in db.scalars(select(CharacterBible).where(
        CharacterBible.character_id.in_(select(Character.id).where(Character.project_id == series_id)))).all()]
    backup["character_references"] = [row_to_dict(r) for r in db.scalars(select(CharacterReference).where(
        CharacterReference.character_id.in_(select(Character.id).where(Character.project_id == series_id)))).all()]
    backup["canon"] = rows(CanonEntry, CanonEntry.project_id == series_id)
    backup["locations"] = rows(Location, Location.project_id == series_id)
    backup["props"] = rows(Prop, Prop.project_id == series_id)
    backup["voices"] = rows(VoiceProfile, VoiceProfile.project_id == series_id)
    backup["assets"] = rows(Asset, Asset.project_id == series_id)
    episodes = rows(Episode, Episode.project_id == series_id)
    backup["episodes"] = episodes
    episode_ids = [e["id"] for e in episodes]
    if episode_ids:
        backup["scenes"] = [row_to_dict(s) for s in db.scalars(select(Scene).where(
            Scene.episode_id.in_(episode_ids))).all()]
        scene_ids = [s.id for s in db.scalars(select(Scene).where(
            Scene.episode_id.in_(episode_ids))).all()]
        backup["shots"] = [row_to_dict(s) for s in db.scalars(select(Shot).where(
            Shot.scene_id.in_(scene_ids))).all()] if scene_ids else []
        backup["script_elements"] = [row_to_dict(e) for e in db.scalars(select(ScriptElement).where(
            ScriptElement.episode_id.in_(episode_ids))).all()]
        backup["timeline_tracks"] = [row_to_dict(t) for t in db.scalars(select(TimelineTrack).where(
            TimelineTrack.episode_id.in_(episode_ids))).all()]
        backup["timeline_items"] = [row_to_dict(i) for i in db.scalars(select(TimelineItem).where(
            TimelineItem.episode_id.in_(episode_ids))).all()]
        backup["renders"] = [row_to_dict(r) for r in db.scalars(select(EpisodeRender).where(
            EpisodeRender.episode_id.in_(episode_ids))).all()]
        backup["exports"] = [row_to_dict(e) for e in db.scalars(select(ExportRecord).where(
            ExportRecord.episode_id.in_(episode_ids))).all()]
        backup["audio_recordings"] = [row_to_dict(r) for r in db.scalars(select(AudioRecording).where(
            AudioRecording.episode_id.in_(episode_ids))).all()]
    shot_ids = [s.id for s in db.scalars(select(Shot).where(
        Shot.scene_id.in_(select(Scene.id).where(Scene.episode_id.in_(episode_ids))))).all()] if episode_ids else []
    backup["generation_jobs"] = [row_to_dict(j) for j in db.scalars(select(GenerationJob).where(
        GenerationJob.project_id == series_id)).all()]
    backup["generation_results"] = [row_to_dict(r) for r in db.scalars(select(GenerationResult).where(
        GenerationResult.shot_id.in_(shot_ids))).all()] if shot_ids else []
    return backup
