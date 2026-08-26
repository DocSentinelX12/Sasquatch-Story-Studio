"""Phase 10: production overview, next-action recommendations, smart generation
planner, character consistency report. Every number comes from the database —
nothing fabricated; no auto-approvals; approved results never overwritten."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Asset,
    AudioRecording,
    Character,
    CharacterReference,
    Episode,
    EpisodeRender,
    ExportRecord,
    GenerationJob,
    GenerationResult,
    Project,
    Scene,
    ScriptElement,
    Season,
    Shot,
    VoiceProfile,
)
from . import postproduction as pp
from .shot_package import validate_shot

# Links into the correct workspace per recommendation
LINKS = {
    "episode": "#/episodes/{id}",
    "scene_director": "#/scenes/{id}/director",
    "generate": "#/generate/{id}",
    "character": "#/characters/{id}",
    "assistant": "#/assistant",
    "timeline": "#/timeline",
    "exports": "#/exports",
    "control": "#/control?tab=series",
}


def production_overview(db: Session) -> dict:
    """All dashboard stats from real queries (Milestone A)."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())  # Monday

    shot_status = dict(db.execute(select(Shot.status, func.count(Shot.id)).group_by(Shot.status)).all())
    results = db.scalars(select(GenerationResult)).all()
    approved_results = {r.shot_id for r in results if r.status == "approved"}

    jobs = db.scalars(select(GenerationJob)).all()
    job_status = {}
    for job in jobs:
        job_status[job.status] = job_status.get(job.status, 0) + 1

    episodes = db.scalars(select(Episode)).all()
    render_ready = 0
    export_ready = 0
    for episode in episodes:
        renders = db.scalars(select(EpisodeRender).where(EpisodeRender.episode_id == episode.id)).all()
        if any(r.status in ("completed", "approved") for r in renders):
            render_ready += 1
        exports = db.scalars(select(ExportRecord).where(
            ExportRecord.episode_id == episode.id, ExportRecord.status == "approved")).all()
        if exports:
            export_ready += 1

    # production activity
    today_jobs = [j for j in jobs if j.created_at and j.created_at >= today]
    week_jobs = [j for j in jobs if j.created_at and j.created_at >= week]
    today_results = [r for r in results if r.created_at and r.created_at >= today]
    week_results = [r for r in results if r.created_at and r.created_at >= week]

    # missing references / voices / QC blockers
    characters = db.scalars(select(Character)).all()
    characters_missing_refs = []
    for character in characters:
        approved = db.scalar(select(func.count(CharacterReference.id)).where(
            CharacterReference.character_id == character.id,
            CharacterReference.approval_status == "approved"))
        if not approved:
            characters_missing_refs.append(character)
    voiced_ids = {v.character_id for v in db.scalars(select(VoiceProfile)).all() if v.character_id}
    characters_missing_voices = [c for c in characters if c.id not in voiced_ids]

    qc_blockers = []
    for episode in episodes:
        qc = pp.qc_check(db, episode.id)
        if qc["blocked"]:
            qc_blockers.append({"episode_id": episode.id, "number": episode.number,
                                "title": episode.title, "blockers": qc["blocked"]})

    failed_jobs = [j for j in jobs if j.status == "failed"]
    waiting_approval = len([r for r in results if r.status == "needs_review"])

    return {
        "series": db.scalar(select(func.count(Project.id))) or 0,
        "seasons": db.scalar(select(func.count(Season.id))) or 0,
        "episodes": len(episodes),
        "shots_total": sum(shot_status.values()),
        "shots": shot_status,
        "ready_to_generate": shot_status.get("ready_for_generation", 0),
        "waiting_for_approval": waiting_approval,
        "generating": job_status.get("generating", 0) + job_status.get("submitted", 0) + job_status.get("submitting", 0),
        "failed_jobs": len(failed_jobs),
        "completed_shots": len(approved_results),
        "render_ready": render_ready,
        "export_ready": export_ready,
        "today": {"jobs": len(today_jobs), "results": len(today_results)},
        "this_week": {"jobs": len(week_jobs), "results": len(week_results)},
        "failed_job_ids": [j.id for j in failed_jobs[:10]],
        "missing_references": [c.name for c in characters_missing_refs],
        "missing_voices": [c.name for c in characters_missing_voices],
        "qc_blockers": qc_blockers,
    }


def next_action_recommendations(db: Session) -> list[dict]:
    """Milestone B: prioritized 'what should I do next?' recommendations.

    Every item comes from real database state — nothing invented, nothing
    approved, nothing published. Read-only.
    """
    recommendations: list[dict] = []

    def add(priority: int, rec_type: str, title: str, message: str,
            entity_type: str, entity_id, link_key: str, action: str, reason: str):
        recommendations.append({
            "priority": priority, "type": rec_type, "title": title,
            "message": message, "entity_type": entity_type, "entity_id": entity_id,
            "route": LINKS[link_key].format(id=entity_id) if "{id}" in LINKS[link_key] else LINKS[link_key],
            "action": action, "reason": reason,
        })

    episodes = db.scalars(select(Episode).order_by(Episode.project_id, Episode.number)).all()

    # --- QC blockers: highest priority (they gate rendering) -------------------
    for episode in episodes:
        qc = pp.qc_check(db, episode.id)
        if qc["blocked"]:
            add(1, "qc_blocker", f"EP-{episode.number:03d} has QC blockers",
                f"{qc['blocked']} blocking issue(s) — resolve or override to render.",
                "episode", episode.id, "timeline", "review QC",
                "Blocking findings prevent Ready-for-Render.")

    # --- failed generations (retryable, deduplicated per shot) ------------------
    failed_jobs = db.scalars(select(GenerationJob).where(
        GenerationJob.status == "failed").order_by(GenerationJob.id.desc())).all()
    seen_shots: set = set()
    for job in failed_jobs:
        if job.shot_id in seen_shots:
            continue
        shot = db.get(Shot, job.shot_id) if job.shot_id else None
        if shot is None:
            continue
        seen_shots.add(shot.id)
        add(2, "failed_generation", f"{shot.shot_ref} failed to generate",
            f"Job #{job.id}: {job.error_code or 'error'} — retry or try another provider.",
            "shot", shot.id, "generate", "retry generation",
            "Failed generations block their shots.")

    # --- shots ready for generation ----------------------------------------------
    ready_shots = db.scalars(select(Shot).where(
        Shot.status == "ready_for_generation").order_by(Shot.scene_id, Shot.order_index)).all()
    if ready_shots:
        sample = ready_shots[0]
        add(3, "ready_to_generate", f"{len(ready_shots)} shot(s) ready for generation",
            f"Next: {sample.shot_ref or 'shot'} — generate from the mobile Generate screen.",
            "shot", sample.id, "generate", "generate video",
            "Shots passed the readiness gate and are waiting.")

    # --- videos awaiting approval --------------------------------------------------
    review_results = db.scalars(select(GenerationResult).where(
        GenerationResult.status == "needs_review").order_by(GenerationResult.id.desc())).all()
    if review_results:
        first = review_results[0]
        shot = db.get(Shot, first.shot_id) if first.shot_id else None
        add(4, "needs_review", f"{len(review_results)} video(s) awaiting approval",
            f"Latest: v{first.version_number}" + (f" of {shot.shot_ref}" if shot else "")
            + " — review, then approve or reject with a reason.",
            "shot", first.shot_id or first.id, "generate", "review video",
            "Approval is always human; results wait for you.")

    # --- scenes needing storyboard preparation --------------------------------------
    for scene in db.scalars(select(Scene).order_by(Scene.episode_id, Scene.order_index)).all():
        if scene.status not in ("approved", "ready_for_storyboard"):
            continue
        shots = db.scalars(select(Shot).where(Shot.scene_id == scene.id)).all()
        if not shots:
            add(5, "storyboard_needed", f"{scene.scene_ref or 'Scene'} has no shots",
                "Build the storyboard from the scene script, then generate.",
                "scene", scene.id, "scene_director", "build storyboard",
                "Approved scene without shots cannot produce video.")
            break  # one representative recommendation

    # --- missing approved references -------------------------------------------------
    characters = db.scalars(select(Character).order_by(Character.name)).all()
    for character in characters:
        approved = db.scalar(select(func.count(CharacterReference.id)).where(
            CharacterReference.character_id == character.id,
            CharacterReference.approval_status == "approved"))
        if not approved:
            add(6, "missing_reference", f"{character.name} has no approved reference",
                "Import creator artwork and approve references — generated shots depend on them.",
                "character", character.id, "character", "add references",
                "Character consistency requires approved references.")

    # --- missing voice profiles --------------------------------------------------------
    voiced_ids = {v.character_id for v in db.scalars(select(VoiceProfile)).all() if v.character_id}
    for character in characters:
        if character.id not in voiced_ids:
            add(7, "missing_voice", f"{character.name} has no voice profile",
                "Create a voice profile once — it is reusable across episodes.",
                "character", character.id, "character", "create voice",
                "Dialogue generation needs an assigned voice.")

    # --- missing audio for script lines ---------------------------------------------------
    for episode in episodes:
        report = _episode_audio_missing(db, episode.id)
        if report["missing"] > 0:
            add(8, "missing_audio",
                f"EP-{episode.number:03d}: {report['missing']} dialogue line(s) need audio",
                "Generate missing dialogue/narration from the Audio workspace.",
                "episode", episode.id, "assistant", "generate audio",
                "Timeline assembly needs approved audio.")
            break  # one representative per run

    # --- episodes ready for render ----------------------------------------------------------
    for episode in episodes:
        qc = pp.qc_check(db, episode.id)
        if qc["status"] in ("pass", "warning") and qc["blocked"] == 0:
            add(9, "render_ready", f"EP-{episode.number:03d} is ready to render",
                "QC passed (warnings may remain) — prepare a render draft.",
                "episode", episode.id, "timeline", "prepare render",
                "QC no longer blocks rendering.")

    # --- remaining exports ---------------------------------------------------------------------
    pending_exports = db.scalars(select(ExportRecord).where(
        ExportRecord.status.notin_(["approved", "exported"])).order_by(ExportRecord.id.desc())).all()
    if pending_exports:
        add(10, "export_pending", f"{len(pending_exports)} export(s) not approved",
            "Review export drafts — approve when the episode is final. Nothing publishes automatically.",
            "episode", pending_exports[0].episode_id or 0, "exports", "review exports",
            "Exports require explicit approval.")

    recommendations.sort(key=lambda r: (r["priority"], str(r["entity_id"])))
    return recommendations[:20]


def _episode_audio_missing(db: Session, episode_id: int) -> dict:
    spoken = db.scalars(select(ScriptElement).join(
        Scene, ScriptElement.scene_id == Scene.id)
        .where(Scene.episode_id == episode_id,
               ScriptElement.element_type.in_(["dialogue", "narration"]))).all()
    missing = 0
    for element in spoken:
        recording = db.scalar(select(AudioRecording.id).where(
            AudioRecording.script_element_id == element.id))
        if recording is None:
            missing += 1
    return {"total_spoken": len(spoken), "missing": missing}


def production_plan(db: Session, episode_id: int | None = None) -> dict:
    """Milestone C: smart, read-only production planner.

    Analyzes real database state through the existing readiness/validation
    gates and returns a structured plan. Never queues, approves, publishes,
    or fabricates — planning only.
    """
    shot_query = select(Shot).join(Scene, Shot.scene_id == Scene.id)
    if episode_id is not None:
        shot_query = shot_query.where(Scene.episode_id == episode_id)
    shots = db.scalars(shot_query.order_by(Scene.order_index, Shot.order_index)).all()

    episode_query = select(Episode).order_by(Episode.project_id, Episode.number)
    if episode_id is not None:
        episode_query = episode_query.where(Episode.id == episode_id)
    episodes = db.scalars(episode_query).all()

    def shot_row(shot: Shot, priority: int, status: str, reason: str) -> dict:
        scene = db.get(Scene, shot.scene_id)
        return {
            "shot_id": shot.id, "episode_id": scene.episode_id if scene else None,
            "scene_id": shot.scene_id, "priority": priority, "status": status,
            "reason": reason, "route": LINKS["generate"].format(id=shot.id),
        }

    ready_shots: list[dict] = []
    blocked_shots: list[dict] = []
    failed_shots: list[dict] = []
    waiting_for_approval: list[dict] = []

    for shot in shots:
        latest_result = db.scalar(select(GenerationResult).where(
            GenerationResult.shot_id == shot.id)
            .order_by(GenerationResult.version_number.desc()))
        latest_job = db.scalar(select(GenerationJob).where(
            GenerationJob.shot_id == shot.id).order_by(GenerationJob.id.desc()))

        # already complete? (approved result, nothing to do)
        if latest_result is not None and latest_result.status == "approved":
            continue

        # failed job that can be retried
        if latest_job is not None and latest_job.status == "failed":
            failed_shots.append(shot_row(shot, 2, "failed",
                f"{latest_job.error_code or 'error'} — retry or switch provider"))
            continue

        # generated, awaiting human approval
        if latest_result is not None and latest_result.status == "needs_review":
            waiting_for_approval.append(shot_row(shot, 5, "needs_review",
                f"v{latest_result.version_number} generated — approve or reject with a reason"))
            continue

        # actively generating / submitted — nothing to do but wait
        if latest_job is not None and latest_job.status in ("submitted", "generating", "submitting"):
            continue

        # passed the readiness gate already
        if shot.status == "ready_for_generation":
            ready_shots.append(shot_row(shot, 3, "ready",
                "Passed validation; generate when ready"))
            continue

        # evaluate against the real gate
        validation = validate_shot(db, shot)
        errors = [f for f in validation["findings"]
                  if f["severity"] == "error" and not f["overridden"]]
        warnings_open = [f for f in validation["findings"]
                         if f["severity"] == "warning" and not f["overridden"]]
        if errors:
            blocked_shots.append(shot_row(shot, 1, "blocked",
                "; ".join(f["key"] for f in errors[:3])))
        elif warnings_open:
            blocked_shots.append(shot_row(shot, 4, "blocked_by_warnings",
                f"{len(warnings_open)} warning(s) — fix or override to proceed"))
        else:
            ready_shots.append(shot_row(shot, 3, "ready_after_gate",
                "Validation clean — approve the shot, then generate"))

    # missing references (characters without approved refs, across scoped episodes)
    scoped_project_ids = {e.project_id for e in episodes} or None
    character_query = select(Character)
    characters = db.scalars(character_query.order_by(Character.name)).all()
    missing_references = []
    for character in characters:
        if scoped_project_ids and character.project_id not in scoped_project_ids:
            continue
        approved = db.scalar(select(func.count(CharacterReference.id)).where(
            CharacterReference.character_id == character.id,
            CharacterReference.approval_status == "approved"))
        if not approved:
            missing_references.append({
                "character_id": character.id, "name": character.name,
                "route": LINKS["character"].format(id=character.id),
                "reason": "no approved reference images",
            })

    # missing audio per episode
    missing_audio = []
    for episode in episodes:
        report = _episode_audio_missing(db, episode.id)
        if report["missing"] > 0:
            missing_audio.append({
                "episode_id": episode.id, "number": episode.number,
                "missing_lines": report["missing"],
                "total_spoken_lines": report["total_spoken"],
                "route": LINKS["assistant"],
            })

    # episode breakdown with QC + render state
    episode_breakdown = []
    for episode in episodes:
        qc = pp.qc_check(db, episode.id)
        episode_shots = db.scalars(select(Shot).join(Scene, Shot.scene_id == Scene.id)
                                   .where(Scene.episode_id == episode.id)).all()
        approved_count = 0
        for shot in episode_shots:
            approved = db.scalar(select(GenerationResult.id).where(
                GenerationResult.shot_id == shot.id,
                GenerationResult.status == "approved"))
            if approved:
                approved_count += 1
        renders = db.scalars(select(EpisodeRender).where(
            EpisodeRender.episode_id == episode.id)).all()
        episode_breakdown.append({
            "episode_id": episode.id, "number": episode.number, "title": episode.title,
            "shots": len(episode_shots), "shots_approved": approved_count,
            "qc_status": qc["status"], "qc_blockers": qc["blocked"],
            "qc_warnings": qc["warnings"],
            "render_versions": len(renders),
            "route": LINKS["episode"].format(id=episode.id),
        })

    # work estimate: count of concrete actionable items (never time/fabricated %)
    estimated_work_items = {
        "blocked_shots": len(blocked_shots),
        "failed_retries": len(failed_shots),
        "ready_to_generate": len(ready_shots),
        "videos_to_review": len(waiting_for_approval),
        "missing_reference_characters": len(missing_references),
        "episodes_missing_audio": len(missing_audio),
    }

    recommended = next_action_recommendations(db)

    return {
        "summary": {
            "scope": f"episode {episode_id}" if episode_id is not None else "all episodes",
            "shots_analyzed": len(shots),
            "ready": len(ready_shots), "blocked": len(blocked_shots),
            "failed": len(failed_shots), "awaiting_approval": len(waiting_for_approval),
            "note": "Read-only plan from real state. No gates bypassed; nothing queued.",
        },
        "recommended_next_actions": recommended[:10],
        "ready_shots": ready_shots,
        "blocked_shots": blocked_shots,
        "failed_shots": failed_shots,
        "waiting_for_approval": waiting_for_approval,
        "missing_references": missing_references,
        "missing_audio": missing_audio,
        "estimated_work_items": estimated_work_items,
        "episode_breakdown": episode_breakdown,
    }



def batch_production_plan(
    db: Session,
    episode_ids: list[int] | None = None,
    include_failed: bool = True,
    include_new_versions: bool = False,
    max_queue_size: int = 100,
) -> dict:
    """Milestone D: read-only batch production plan.

    Uses the Phase 7 batch-generation rules and the existing readiness gates.
    This plans only — it never creates jobs, queues anything, approves
    anything, or changes statuses.
    """
    max_queue_size = max(1, min(int(max_queue_size), 500))  # safe bounds

    shot_query = select(Shot).join(Scene, Shot.scene_id == Scene.id)
    if episode_ids:
        shot_query = shot_query.where(Scene.episode_id.in_(episode_ids))
    shots = db.scalars(shot_query.order_by(Scene.order_index, Shot.order_index)).all()

    episode_query = select(Episode).order_by(Episode.project_id, Episode.number)
    if episode_ids:
        episode_query = episode_query.where(Episode.id.in_(episode_ids))
    episodes = db.scalars(episode_query).all()
    project_ids = {e.project_id for e in episodes}

    queue: list[dict] = []
    blocked: list[dict] = []
    requires_approval: list[dict] = []
    missing_requirements: list[dict] = []
    seen: set[int] = set()

    def row(shot: Shot, priority: int, reason: str, action: str, eligible: bool) -> dict:
        scene = db.get(Scene, shot.scene_id)
        return {
            "shot_id": shot.id,
            "episode_id": scene.episode_id if scene else None,
            "scene_id": shot.scene_id,
            "priority": priority,
            "reason": reason,
            "action": action,
            "route": LINKS["generate"].format(id=shot.id),
            "eligible": eligible,
        }

    counts = {"total_scanned": len(shots), "eligible": 0, "blocked": 0,
              "failed": 0, "waiting_for_approval": 0, "missing_requirements": 0}

    for shot in shots:
        if shot.id in seen:
            continue
        seen.add(shot.id)

        latest_result = db.scalar(select(GenerationResult).where(
            GenerationResult.shot_id == shot.id)
            .order_by(GenerationResult.version_number.desc()))
        latest_job = db.scalar(select(GenerationJob).where(
            GenerationJob.shot_id == shot.id).order_by(GenerationJob.id.desc()))

        # 1. approved/completed shots excluded unless new versions requested
        if latest_result is not None and latest_result.status == "approved":
            if not include_new_versions:
                continue
            queue.append(row(shot, 4,
                f"approved v{latest_result.version_number}; new version explicitly requested",
                "queue_new_version", eligible=True))
            counts["eligible"] += 1
            continue

        # 2. retryable failed shots
        if latest_job is not None and latest_job.status == "failed":
            if include_failed:
                queue.append(row(shot, 2,
                    f"{latest_job.error_code or 'error'} — retryable",
                    "retry_generation", eligible=True))
                counts["eligible"] += 1
                counts["failed"] += 1
            else:
                blocked.append(row(shot, 2,
                    f"{latest_job.error_code or 'error'} — failed (retries excluded by request)",
                    "review_failure", eligible=False))
            continue

        # waiting for human approval — never silently promoted
        if latest_result is not None and latest_result.status == "needs_review":
            requires_approval.append(row(shot, 3,
                f"v{latest_result.version_number} generated — human review required",
                "review_video", eligible=False))
            counts["waiting_for_approval"] += 1
            continue

        # actively generating — not actionable
        if latest_job is not None and latest_job.status in ("submitted", "generating", "submitting"):
            continue

        # 3/4. run the real gate
        validation = validate_shot(db, shot)
        errors = [f for f in validation["findings"]
                  if f["severity"] == "error" and not f["overridden"]]
        warnings_open = [f for f in validation["findings"]
                         if f["severity"] == "warning" and not f["overridden"]]

        if errors:
            blocked.append(row(shot, 1,
                "; ".join(f["key"] for f in errors[:3]),
                "resolve_blockers", eligible=False))
            counts["blocked"] += 1
            for finding in errors:
                if "reference" in finding["key"] or "cast" in finding["key"]:
                    missing_requirements.append({
                        "shot_id": shot.id, "kind": "reference",
                        "detail": finding["message"][:120],
                        "route": LINKS["generate"].format(id=shot.id)})
        elif warnings_open:
            blocked.append(row(shot, 1,
                f"{len(warnings_open)} warning(s) — fix or override to pass the gate",
                "resolve_warnings", eligible=False))
            counts["blocked"] += 1
        else:
            if shot.status == "ready_for_generation":
                queue.append(row(shot, 3, "passed the readiness gate",
                                 "queue_generation", eligible=True))
                counts["eligible"] += 1
            else:
                requires_approval.append(row(shot, 3,
                    "validation clean — approve the shot (human gate), then generate",
                    "approve_shot", eligible=False))
                counts["waiting_for_approval"] += 1

    # 5. missing character references for scoped projects
    for character in db.scalars(select(Character).order_by(Character.name)).all():
        if project_ids and character.project_id not in project_ids:
            continue
        approved = db.scalar(select(func.count(CharacterReference.id)).where(
            CharacterReference.character_id == character.id,
            CharacterReference.approval_status == "approved"))
        if not approved:
            missing_requirements.append({
                "character_id": character.id, "kind": "character_reference",
                "detail": f"{character.name} has no approved reference images",
                "route": LINKS["character"].format(id=character.id)})
    counts["missing_requirements"] = len(missing_requirements)

    # 9. priority order, 12. configurable cap with safe default
    queue.sort(key=lambda r: (r["priority"], r["shot_id"]))
    queue = queue[:max_queue_size]
    blocked.sort(key=lambda r: (r["priority"], r["shot_id"]))

    # per-episode summary (reuses Milestone C)
    episode_rows = []
    for episode in episodes:
        plan = production_plan(db, episode.id)
        breakdown = plan["episode_breakdown"][0] if plan["episode_breakdown"] else {}
        episode_rows.append({
            "episode_id": episode.id, "number": episode.number, "title": episode.title,
            "shots": breakdown.get("shots", 0),
            "shots_approved": breakdown.get("shots_approved", 0),
            "qc_status": breakdown.get("qc_status", "unknown"),
            "qc_blockers": breakdown.get("qc_blockers", 0),
            "route": LINKS["episode"].format(id=episode.id),
        })

    return {
        "summary": {
            **counts,
            "scope": f"episodes {episode_ids}" if episode_ids else "all episodes",
            "include_failed": include_failed,
            "include_new_versions": include_new_versions,
            "max_queue_size": max_queue_size,
            "note": "Read-only plan. No jobs created, nothing queued or approved; "
                    "no fabricated time, credits, or completion estimates.",
        },
        "episodes": episode_rows,
        "queue": queue,
        "blocked": blocked,
        "requires_approval": requires_approval,
        "missing_requirements": missing_requirements,
    }



def smart_generation_plan(
    db: Session,
    episode_ids: list[int] | None = None,
    max_queue_size: int = 100,
    include_failed: bool = True,
    include_new_versions: bool = False,
) -> dict:
    """Milestone E: smart generation planner (read-only).

    Determines WHAT TO GENERATE NEXT using real database state. Reuses
    batch_production_plan() for eligibility so the gate rules are never
    duplicated or bypassed. Never creates, queues, approves, or publishes.
    """
    # --- reuse Milestone D classification (single source of gate truth) -------
    base = batch_production_plan(db, episode_ids=episode_ids,
                                 include_failed=include_failed,
                                 include_new_versions=include_new_versions,
                                 max_queue_size=500)  # analyze broadly, cap later

    scene_ids = {item["scene_id"] for item in
                 base["queue"] + base["blocked"] + base["requires_approval"]}
    episodes_involved = {item["episode_id"] for item in
                         base["queue"] + base["blocked"] + base["requires_approval"]}

    # --- real completion counts per scene and episode ------------------------
    def scene_stats(scene_id: int) -> dict:
        shots = db.scalars(select(Shot).where(Shot.scene_id == scene_id)).all()
        approved = ready = failed = review = 0
        for shot in shots:
            result = db.scalar(select(GenerationResult).where(
                GenerationResult.shot_id == shot.id)
                .order_by(GenerationResult.version_number.desc()))
            job = db.scalar(select(GenerationJob).where(
                GenerationJob.shot_id == shot.id).order_by(GenerationJob.id.desc()))
            if result is not None and result.status == "approved":
                approved += 1
            elif job is not None and job.status == "failed":
                failed += 1
            elif result is not None and result.status == "needs_review":
                review += 1
            elif shot.status == "ready_for_generation":
                ready += 1
        total = len(shots)
        remaining = total - approved
        ratio = round(approved / total, 3) if total else 0.0
        return {"total": total, "approved": approved, "ready": ready,
                "failed": failed, "review": review, "remaining": remaining,
                "completion_ratio_calculated": ratio}

    def episode_stats(episode_id: int) -> dict:
        shots = db.scalars(select(Shot).join(Scene, Shot.scene_id == Scene.id)
                           .where(Scene.episode_id == episode_id)).all()
        approved = sum(1 for shot in shots if db.scalar(select(GenerationResult.id).where(
            GenerationResult.shot_id == shot.id,
            GenerationResult.status == "approved")))
        total = len(shots)
        return {"total": total, "approved": approved, "remaining": total - approved,
                "completion_ratio_calculated": round(approved / total, 3) if total else 0.0}

    stats_cache: dict[int, dict] = {}
    for sid in scene_ids:
        stats_cache[sid] = scene_stats(sid)
    ep_cache: dict[int, dict] = {}
    for eid in episodes_involved:
        if eid is not None:
            ep_cache[eid] = episode_stats(eid)

    blocked_by_scene: dict[int, int] = {}
    for item in base["blocked"]:
        blocked_by_scene[item["scene_id"]] = blocked_by_scene.get(item["scene_id"], 0) + 1
    review_by_scene: dict[int, int] = {}
    for item in base["requires_approval"]:
        review_by_scene[item["scene_id"]] = review_by_scene.get(item["scene_id"], 0) + 1

    def score_item(item: dict) -> tuple:
        """SMART priority: base tier + production-aware completion boost."""
        base_priority = item["priority"]  # 1 blockers, 2 retries, 3 ready, 4 new-version
        stats = stats_cache.get(item["scene_id"], {})
        remaining = stats.get("remaining", 999)
        ep = ep_cache.get(item["episode_id"], {})
        ep_remaining = ep.get("remaining", 999)
        blockers = blocked_by_scene.get(item["scene_id"], 0)
        return (base_priority, remaining, ep_remaining, blockers, item["shot_id"])

    # --- build recommended_next from eligible queue items only -----------------
    from ..services.batch import classify_failure

    recommended_next: list[dict] = []
    for item in base["queue"]:
        recommendation = {
            "shot_id": item["shot_id"],
            "episode_id": item["episode_id"],
            "scene_id": item["scene_id"],
            "priority": item["priority"],
            "recommendation": "",
            "reason": item["reason"],
            "action": item["action"],
            "route": item["route"],
            "eligible": item["eligible"],
        }
        stats = stats_cache.get(item["scene_id"], {})
        if item["action"] == "retry_generation":
            job = db.scalar(select(GenerationJob).where(
                GenerationJob.shot_id == item["shot_id"])
                .order_by(GenerationJob.id.desc()))
            classification = classify_failure(job.error_code if job else None)
            if not classification.get("allowed", False):
                recommendation["eligible"] = False
                recommendation["action"] = "manual_review_failure"
                recommendation["reason"] += (
                    " - " + str(classification.get("classification", "unknown"))
                    + " failure, not auto-retryable (manual decision required)")
                recommendation["recommendation"] = "Review failure manually"
            else:
                recommendation["recommendation"] = "Retry failed generation"
        elif item["action"] == "queue_new_version":
            recommendation["recommendation"] = (
                "Generate new version (the approved version is kept, never replaced)")
        else:
            recommendation["recommendation"] = "Generate shot"
        if stats:
            recommendation["reason"] += (
                " . scene " + str(stats.get("approved", 0)) + "/"
                + str(stats.get("total", 0)) + " approved ("
                + str(stats.get("remaining", 0)) + " remaining)")
        recommended_next.append(recommendation)

    recommended_next.sort(key=score_item)
    hard_cap = max(1, min(int(max_queue_size), 500))
    recommended_next = recommended_next[:hard_cap]

    # non-eligible items are demoted honestly into requires_approval
    demoted = [r for r in recommended_next if not r["eligible"]]
    for item in demoted:
        base["requires_approval"].append({
            "shot_id": item["shot_id"], "episode_id": item["episode_id"],
            "scene_id": item["scene_id"], "priority": item["priority"],
            "reason": item["reason"], "action": "manual_review_failure",
            "route": item["route"], "eligible": False})
    recommended_next = [r for r in recommended_next if r["eligible"]]

    # --- per-episode view -------------------------------------------------------
    by_episode = []
    episode_query = select(Episode).order_by(Episode.project_id, Episode.number)
    if episode_ids:
        episode_query = episode_query.where(Episode.id.in_(episode_ids))
    for episode in db.scalars(episode_query).all():
        stats = episode_stats(episode.id)
        ep_recommended = [r for r in recommended_next if r["episode_id"] == episode.id]
        by_episode.append({
            "episode_id": episode.id, "number": episode.number, "title": episode.title,
            "shots": stats["total"], "approved": stats["approved"],
            "remaining": stats["remaining"],
            "completion_ratio_calculated": stats["completion_ratio_calculated"],
            "recommended_now": len(ep_recommended),
            "route": LINKS["episode"].format(id=episode.id),
        })

    return {
        "summary": {
            "episodes_scanned": len(base["episodes"]),
            "shots_scanned": base["summary"]["total_scanned"],
            "recommended": len(recommended_next),
            "blocked": base["summary"]["blocked"],
            "failed": base["summary"]["failed"],
            "waiting_for_approval": base["summary"]["waiting_for_approval"],
            "missing_requirements": base["summary"]["missing_requirements"],
            "note": "Read-only smart plan. Ratios are calculated database ratios. "
                    "Nothing queued, approved, or published; approved versions never replaced.",
        },
        "recommended_next": recommended_next,
        "by_episode": by_episode,
        "blocked": base["blocked"],
        "requires_approval": base["requires_approval"],
        "missing_requirements": base["missing_requirements"],
    }



# ---------------------------------------------------------------------------
# Milestone G: character consistency report (read-only)
# ---------------------------------------------------------------------------

# Fields on Character that carry canon/continuity information. Empty optional
# fields are a WARNING (missing info), never a blocker by themselves.
_CONSISTENCY_FIELDS = (
    ("standard_appearance", "Standard appearance"),
    ("current_outfit", "Current outfit"),
    ("standard_props", "Standard props"),
    ("personality_rules", "Personality rules"),
    ("visual_rules", "Visual rules"),
    ("never_changes", "Never-changes rules"),
)

_BAREFOOT_TERMS = ("shoes", "boots", "socks", "sandals", "slippers", "sneakers", "heels",
                   "footwear", "barefoot")


def character_consistency_report(
    db: Session,
    character_id: int | None = None,
    episode_id: int | None = None,
    scene_id: int | None = None,
) -> dict:
    """Milestone G: read-only character consistency report.

    Compares stored canon/continuity data against actual production data
    (casting, shot references, packages) using only what exists in the
    database. Never creates, queues, approves, or modifies anything.
    """
    from ..models import (CanonEntry, CharacterReference, ContinuityRecord,
                          GenerationResult, Prop, SceneCharacter, ShotCharacter)

    # --- validate filters cleanly -------------------------------------------
    if character_id is not None and db.get(Character, character_id) is None:
        raise ValueError(f"Unknown character id {character_id}")
    if episode_id is not None and db.get(Episode, episode_id) is None:
        raise ValueError(f"Unknown episode id {episode_id}")
    if scene_id is not None and db.get(Scene, scene_id) is None:
        raise ValueError(f"Unknown scene id {scene_id}")

    character_query = select(Character).order_by(Character.project_id, Character.name)
    if character_id is not None:
        character_query = character_query.where(Character.id == character_id)
    characters = db.scalars(character_query).all()

    # scene scope: explicit scene > scenes of an episode > all scenes
    scoped_scene_ids: set[int] | None = None
    if scene_id is not None:
        scoped_scene_ids = {scene_id}
    elif episode_id is not None:
        scoped_scene_ids = set(db.scalars(select(Scene.id).where(
            Scene.episode_id == episode_id)).all())

    findings: list[dict] = []
    affected_scene_ids: set[int] = set()
    affected_shot_ids: set[int] = set()
    missing_references = 0
    missing_rules = 0

    barefoot_canon = db.scalar(select(CanonEntry.statement).where(
        CanonEntry.title == "Barefoot rule"))

    def add(severity, f_type, character, message, reason, route_key, action,
            episode=None, scene=None, shot=None):
        route = LINKS.get(route_key, LINKS["character"])
        if "{id}" in route:
            link_id = shot or scene or episode or character.id
            route = route.format(id=link_id)
        findings.append({
            "severity": severity, "type": f_type,
            "character_id": character.id,
            "episode_id": episode, "scene_id": scene, "shot_id": shot,
            "message": message, "reason": reason,
            "route": route, "action": action,
        })

    for character in characters:
        ep_scope = episode_id

        # 1. lifecycle status -------------------------------------------------
        if character.life_status == "archived":
            scene_links = db.scalars(select(SceneCharacter).where(
                SceneCharacter.character_id == character.id)).all()
            if scene_links:
                add("blocker", "lifecycle", character,
                    f"Archived character {character.name} is still cast in scenes",
                    "Archived characters should not receive new production work",
                    "character", "review casting")
                for link in scene_links:
                    affected_scene_ids.add(link.scene_id)
        elif character.life_status == "draft":
            add("info", "lifecycle", character,
                f"{character.name} is still a draft character",
                "Draft characters can be cast but are not canon-verified",
                "character", "finalize character")

        # 2. approved reference availability ------------------------------------
        approved_refs = db.scalars(select(CharacterReference).where(
            CharacterReference.character_id == character.id,
            CharacterReference.approval_status == "approved")).all()
        if not approved_refs:
            missing_references += 1
            add("warning", "missing_reference", character,
                f"{character.name} has no approved reference images",
                "Generation packages will contain no character reference images; "
                "identity consistency relies on prompts alone",
                "character", "add and approve references")
        else:
            has_primary = any(r.is_primary for r in approved_refs)
            if not has_primary:
                add("info", "reference_primary", character,
                    f"{character.name} has {len(approved_refs)} approved reference(s) but none marked primary",
                    "Reference packages prioritize a primary image when present",
                    "character", "mark a primary reference")

        # 3-8. canon/continuity field availability ---------------------------------
        character_missing_rules = 0
        for field_name, label in _CONSISTENCY_FIELDS:
            value = getattr(character, field_name, None)
            if value in (None, "", [], {}):
                character_missing_rules += 1
                add("warning", "missing_" + field_name, character,
                    f"{character.name} has no {label.lower()} recorded",
                    f"{label} is optional but improves generation consistency",
                    "character", f"fill in {label.lower()}")
        missing_rules += character_missing_rules

        # 9. relationships -----------------------------------------------------------
        relationship_count = len(character.outgoing_relationships or [])
        if relationship_count == 0 and character.character_kind == "person":
            add("info", "relationships", character,
                f"{character.name} has no recorded relationships",
                "Relationships feed the Scene/Shot continuity packages",
                "character", "add relationships")

        # 10. scene casting within scope ------------------------------------------------
        scene_links = db.scalars(select(SceneCharacter).where(
            SceneCharacter.character_id == character.id)).all()
        if scoped_scene_ids is not None:
            scene_links = [l for l in scene_links if l.scene_id in scoped_scene_ids]
        for link in scene_links:
            scene = db.get(Scene, link.scene_id)
            if scene is None:
                continue
            affected_scene_ids.add(scene.id)
            # cast in a scene whose location has no approved reference assets
            if scene.location_id is not None:
                from ..models import Asset, Location
                location = db.get(Location, scene.location_id)
                if location is not None:
                    bg = db.scalar(select(Asset.id).where(
                        Asset.location_id == location.id, Asset.status == "approved"))
                    if bg is None:
                        add("info", "scene_location_reference", character,
                            f"{character.name} appears in a scene whose location "
                            f"'{location.name}' has no approved background reference",
                            "Optional, but location references improve consistency",
                            "scene_director", "add location reference",
                            episode=scene.episode_id, scene=scene.id)

        # 11-12. shot casting + approved references in generation packages -----------------
        shot_links = db.scalars(select(ShotCharacter).where(
            ShotCharacter.character_id == character.id)).all()
        for link in shot_links:
            shot = db.get(Shot, link.shot_id)
            if shot is None:
                continue
            if scoped_scene_ids is not None and shot.scene_id not in scoped_scene_ids:
                continue
            scene = db.get(Scene, shot.scene_id)
            affected_shot_ids.add(shot.id)
            # the actual generation gate check for this shot (reuses validate_shot)
            from .shot_package import validate_shot as _validate
            validation = _validate(db, shot)
            for finding in validation["findings"]:
                if finding["severity"] == "error" and not finding["overridden"] and (
                        finding["key"].startswith("character-") and str(character.id) in finding["key"]):
                    add("blocker", "shot_gate", character,
                        f"Shot {shot.shot_ref or shot.id} blocked: {finding['message']}",
                        finding["key"], "generate", "resolve before generating",
                        episode=scene.episode_id if scene else None,
                        scene=shot.scene_id, shot=shot.id)

        # 13. character-owned props ------------------------------------------------------------
        owned_props = db.scalars(select(Prop).where(
            Prop.owner_character_id == character.id)).all()
        for prop in owned_props:
            if prop.approval_status != "approved":
                add("warning", "prop_approval", character,
                    f"Prop '{prop.name}' owned by {character.name} is not approved",
                    "Unapproved props in packages risk inconsistent depictions",
                    "character", "approve the prop")

        # 14. character-related continuity events --------------------------------------------------
        events = db.scalars(select(ContinuityRecord).where(
            ContinuityRecord.kind.in_(["clothing", "injury", "relationship",
                                       "character_location", "event", "discovery"]))).all()
        char_events = []
        for event in events:
            details = event.details or {}
            if details.get("character_id") == character.id or (
                    isinstance(details.get("characters"), list)
                    and character.id in details.get("characters", [])):
                char_events.append(event)
        for event in char_events:
            if event.status != "canon":
                add("info", "continuity_event", character,
                    f"Draft continuity event for {character.name}: {event.summary[:80]}",
                    "Draft events are not yet canon; approve them when confirmed",
                    "assistant", "review continuity event")

        # 15. barefoot canon vs stored character data ---------------------------------------------------
        if barefoot_canon:
            text_blob = " ".join(filter(None, [
                character.current_outfit, character.clothing,
                character.standard_appearance])).lower()
            for term in _BAREFOOT_TERMS:
                if term in text_blob and term != "barefoot":
                    idx = text_blob.find(term)
                    context = text_blob[max(0, idx - 25):idx + len(term) + 5]
                    if "barefoot" not in context and "no " + term.split()[0] not in context:
                        add("blocker", "barefoot_canon", character,
                            f"Possible footwear mention ('{term}') in {character.name}'s stored outfit/appearance data",
                            "Contradicts the stored barefoot canon rule",
                            "character", "remove the footwear reference")
                        break

    # 16-17. cross-checks are embedded above (production vs canon contradictions
    # appear as blocker findings; missing info as warnings).

    # deduplicate identical findings (same severity+type+character+scene+shot+message)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for finding in findings:
        key = (finding["severity"], finding["type"], finding["character_id"],
               finding["scene_id"], finding["shot_id"], finding["message"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)

    severity_order = {"blocker": 0, "warning": 1, "info": 2}
    deduped.sort(key=lambda f: (severity_order[f["severity"]], f["character_id"] or 0,
                                f["type"], f["scene_id"] or 0, f["shot_id"] or 0))

    blockers = [f for f in deduped if f["severity"] == "blocker"]
    warnings = [f for f in deduped if f["severity"] == "warning"]
    infos = [f for f in deduped if f["severity"] == "info"]

    return {
        "character": (row_to_dict_character(characters[0])
                      if character_id is not None and characters else None),
        "summary": {
            "characters_scanned": len(characters),
            "blockers": len(blockers),
            "warnings": len(warnings),
            "info": len(infos),
            "missing_references": missing_references,
            "missing_rules": missing_rules,
            "affected_scenes": len(affected_scene_ids),
            "affected_shots": len(affected_shot_ids),
            "note": "Read-only report from stored data. No percentages, time "
                    "estimates, or confidence scores — only concrete counts.",
        },
        "findings": deduped,
        "affected_scenes": sorted(affected_scene_ids),
        "affected_shots": sorted(affected_shot_ids),
    }


def row_to_dict_character(character: Character) -> dict:
    return {
        "id": character.id, "char_ref": character.char_ref, "name": character.name,
        "species": character.species, "life_status": character.life_status,
        "approval_status": character.approval_status, "is_canon": character.is_canon,
    }
