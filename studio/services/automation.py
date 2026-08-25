"""Phase 8 automation engine: safe, audited, never approves or publishes.

emit_event() is called from approval/generation/QC code paths. Rules matching
the trigger + conditions run their actions; every run lands in the audit log
with per-action results. Dry-run records what WOULD happen without doing it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AutomationAudit,
    AutomationRule,
    Episode,
    GenerationResult,
    Notification,
    Scene,
    Shot,
)
from . import postproduction as pp

PROJECT_PAUSES: set[int] = set()   # in-memory pause flags (also surfaced via API)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def production_paused(project_id: int | None) -> bool:
    return project_id in PROJECT_PAUSES if project_id else False


def set_production_paused(project_id: int | None, paused: bool) -> None:
    if project_id is None:
        return
    if paused:
        PROJECT_PAUSES.add(project_id)
    else:
        PROJECT_PAUSES.discard(project_id)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def emit_event(db: Session, event: str, project_id: int | None = None,
               episode_id: int | None = None, scene_id: int | None = None,
               shot_id: int | None = None, context: dict | None = None) -> list[dict]:
    """Run enabled rules matching this event. Returns audit summaries."""
    if event not in (  # imported lazily to avoid cycles
        "shot_approved", "audio_approved", "scene_complete", "episode_ready",
        "generation_failed", "generation_succeeded", "qc_warning", "qc_blocker",
    ):
        return []
    rules = db.scalars(select(AutomationRule).where(
        AutomationRule.enabled == True,  # noqa: E712
        AutomationRule.trigger == event,
    ).order_by(AutomationRule.priority)).all()
    results = []
    for rule in rules:
        if rule.project_id is not None and project_id is not None and rule.project_id != project_id:
            continue
        if not conditions_match(rule.conditions or {}, episode_id=episode_id,
                                scene_id=scene_id, shot_id=shot_id):
            continue
        try:
            summary = execute_rule(db, rule, event, project_id=project_id,
                                   episode_id=episode_id, scene_id=scene_id,
                                   shot_id=shot_id, context=context or {})
        except Exception as error:  # noqa: BLE001 - log, never crash the caller
            summary = _audit(db, rule, event, target=_target(db, episode_id, scene_id, shot_id),
                             actions=[{"action": "engine-error", "result": str(error)[:200]}],
                             dry_run=rule.dry_run, outcome="error")
        results.append({"rule_id": rule.id, "name": rule.name,
                        "audit_id": summary.id if summary else None})
    return results


def conditions_match(conditions: dict, episode_id=None, scene_id=None, shot_id=None) -> bool:
    if conditions.get("episode_id") and episode_id and conditions["episode_id"] != episode_id:
        return False
    if conditions.get("scene_id") and scene_id and conditions["scene_id"] != scene_id:
        return False
    if conditions.get("shot_id") and shot_id and conditions["shot_id"] != shot_id:
        return False
    return True  # numeric thresholds (min approvals etc.) are evaluated in actions


def execute_rule(db: Session, rule: AutomationRule, event: str, project_id=None,
                 episode_id=None, scene_id=None, shot_id=None, context: dict | None = None,
                 force_dry_run: bool = False) -> AutomationAudit:
    dry = rule.dry_run or force_dry_run
    actions_taken = []
    for spec in rule.actions or []:
        if isinstance(spec, str):
            spec = {"action": spec}
        action = spec.get("action", "")
        result = _run_action(db, action, spec.get("params", {}), dry=dry,
                             project_id=project_id, episode_id=episode_id,
                             scene_id=scene_id, shot_id=shot_id, context=context or {})
        actions_taken.append({"action": action, "result": result})
    outcome = "dry-run" if dry else "executed"
    if any(str(a["result"]).startswith(("blocked", "error")) for a in actions_taken):
        outcome += " (with issues)"
    audit = _audit(db, rule, event, target=_target(db, episode_id, scene_id, shot_id),
                   actions=actions_taken, dry_run=dry, outcome=outcome)
    rule.run_count = (rule.run_count or 0) + 1
    rule.last_run_at = utcnow_iso()
    db.commit()
    return audit


def _target(db: Session, episode_id, scene_id, shot_id) -> str | None:
    if shot_id:
        shot = db.get(Shot, shot_id)
        if shot:
            return shot.shot_ref or f"Shot {shot.id}"
    if scene_id:
        scene = db.get(Scene, scene_id)
        if scene:
            return scene.scene_ref or f"Scene {scene.id}"
    if episode_id:
        episode = db.get(Episode, episode_id)
        if episode:
            return f"EP-{episode.number:03d}"
    return None


def _audit(db: Session, rule, event, target, actions, dry_run, outcome) -> AutomationAudit:
    entry = AutomationAudit(
        rule_id=rule.id if rule is not None else None,
        rule_name=rule.name if rule is not None else "(manual)",
        trigger_event=event, target=target, dry_run=dry_run,
        actions_taken=actions, outcome=outcome)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# Actions — prepare/queue only; no approvals, no publishing
# ---------------------------------------------------------------------------

def _episode_for(db: Session, episode_id=None, scene_id=None, shot_id=None):
    if episode_id:
        return db.get(Episode, episode_id)
    if scene_id:
        scene = db.get(Scene, scene_id)
        return db.get(Episode, scene.episode_id) if scene else None
    if shot_id:
        shot = db.get(Shot, shot_id)
        if shot:
            scene = db.get(Scene, shot.scene_id)
            return db.get(Episode, scene.episode_id) if scene else None
    return None


def _run_action(db: Session, action: str, params: dict, *, dry: bool,
                project_id=None, episode_id=None, scene_id=None, shot_id=None,
                context: dict | None = None) -> str:
    context = context or {}
    episode = _episode_for(db, episode_id, scene_id, shot_id)

    if action == "queue_next_shot":
        if production_paused(project_id):
            return "blocked: production paused"
        from . import generation_service
        if episode is None:
            return "error: no episode context"
        shots = db.scalars(select(Shot).join(Scene, Shot.scene_id == Scene.id)
                           .where(Scene.episode_id == episode.id).order_by(Scene.order_index, Shot.order_index)).all()
        for candidate in shots:
            latest = db.scalar(select(GenerationResult).where(
                GenerationResult.shot_id == candidate.id)
                .order_by(GenerationResult.version_number.desc()))
            if latest is None or latest.status != "approved":
                if candidate.status not in ("ready_for_generation", "generating", "generated",
                                            "needs_revision", "complete"):
                    return f"blocked: {candidate.shot_ref} not ready (needs the technical gate)"
                if dry:
                    return f"would queue {candidate.shot_ref}"
                try:
                    job = generation_service.create_job(db, candidate.id, "auto", {})
                    generation_service.submit_job(job.id)
                    return f"queued {candidate.shot_ref} as job #{job.id}"
                except Exception as error:  # noqa: BLE001
                    return f"error: {str(error)[:120]}"
        return "no shots pending"

    if action == "queue_missing_audio":
        if production_paused(project_id):
            return "blocked: production paused"
        from . import batch as batch_service
        if episode is None:
            return "error: no episode context"
        report = batch_service.batch_audio_report(db, episode.id)
        if dry:
            return f"would queue {report['missing']} missing line(s)"
        result = batch_service.queue_batch_audio(db, episode.id)
        return f"queued {len(result['queued'])}, skipped {len(result['skipped'])}"

    if action == "run_qc":
        if episode is None:
            return "error: no episode context"
        qc = pp.qc_check(db, episode.id)
        if dry:
            return f"would run QC ({qc['blocked']} blockers, {qc['warnings']} warnings)"
        db.add(Notification(project_id=project_id, kind="automation",
                            message=f"QC run for EP-{episode.number:03d}: {qc['blocked']} blockers, {qc['warnings']} warnings",
                            link=f"#/timeline"))
        db.commit()
        return f"{qc['blocked']} blockers, {qc['warnings']} warnings"

    if action == "prepare_render":
        if episode is None:
            return "error: no episode context"
        qc = pp.qc_check(db, episode.id)
        if qc["blocked"]:
            return f"blocked: QC has {qc['blocked']} blocker(s) — resolve or override first"
        if dry:
            return "would create a DRAFT render (rendering itself stays manual)"
        render = pp.create_render(db, episode.id)
        return f"draft render v{render.version_number} created (not queued)"

    if action == "notify_user":
        message = params.get("message") or f"Automation: {context.get('note', 'production event')}"
        if dry:
            return f"would notify: {message}"
        db.add(Notification(project_id=project_id, kind="automation", message=message,
                            link=params.get("link")))
        db.commit()
        return "notified"

    if action == "pause_production":
        if dry:
            return "would pause batch production for this series"
        set_production_paused(project_id, True)
        db.add(Notification(project_id=project_id, kind="warning",
                            message="Production paused by automation rule (resume in Control Center).",
                            link="#/assistant"))
        db.commit()
        return "paused"

    if action == "mark_episode_review":
        if episode is None:
            return "error: no episode context"
        if dry:
            return f"would flag EP-{episode.number:03d} for human review"
        db.add(Notification(project_id=project_id, kind="warning",
                            message=f"EP-{episode.number:03d} flagged for human review by rule.",
                            link=f"#/episodes/{episode.id}"))
        db.commit()
        return "flagged for review"

    return f"error: unknown action '{action}'"


# ---------------------------------------------------------------------------
# Scene-completeness helper used by the shot_approved hook
# ---------------------------------------------------------------------------

def scene_complete(db: Session, scene_id: int) -> bool:
    shots = db.scalars(select(Shot).where(Shot.scene_id == scene_id)).all()
    if not shots:
        return False
    for shot in shots:
        approved = db.scalar(select(GenerationResult.id).where(
            GenerationResult.shot_id == shot.id, GenerationResult.status == "approved"))
        if not approved:
            return False
    return True


DEFAULT_RULES = [
    {"name": "Scene complete → run QC", "trigger": "scene_complete",
     "actions": [{"action": "run_qc"}, {"action": "notify_user", "params": {"message": "A scene reached completion — QC recorded."}}],
     "description": "When every shot in a scene has an approved result, run QC and record it."},
    {"name": "Generation failed → notify", "trigger": "generation_failed",
     "actions": [{"action": "notify_user", "params": {"message": "A generation failed — check the queue."}}],
     "description": "Never auto-retries failures; just tells you."},
    {"name": "Episode ready → prepare draft render", "trigger": "episode_ready",
     "actions": [{"action": "prepare_render"}, {"action": "notify_user"}],
     "description": "Creates a DRAFT render only; rendering and publishing stay manual."},
]


def seed_default_rules(db: Session, project_id: int | None = None) -> int:
    created = 0
    for spec in DEFAULT_RULES:
        exists = db.scalar(select(AutomationRule).where(
            AutomationRule.name == spec["name"],
            AutomationRule.project_id == project_id))
        if exists is None:
            db.add(AutomationRule(project_id=project_id, name=spec["name"],
                                  description=spec.get("description"), enabled=False,
                                  trigger=spec["trigger"], actions=spec["actions"],
                                  priority=10, dry_run=False))
            created += 1
    db.commit()
    return created
