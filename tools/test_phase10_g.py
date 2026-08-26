"""Milestone G focused tests: character_consistency_report.
Run: .venv/bin/python tools/test_phase10_g.py"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from studio.server import app  # noqa: E402
from studio.db import create_all, SessionLocal  # noqa: E402
from studio.services.seed import seed_if_empty, seed_story_layer, backfill_canon_fields  # noqa: E402
from studio.services.planner import character_consistency_report  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from studio.models import (Character, Episode, Scene, Shot, GenerationJob,  # noqa: E402
                           GenerationResult, SceneCharacter)

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    print(("PASS" if cond else "FAIL"), "-", name, extra if not cond else "")
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (0 if cond else 1)


create_all()
session = SessionLocal()
seed_if_empty(session)
seed_story_layer(session)
backfill_canon_fields(session)

MODELS = (Character, Episode, Scene, Shot, GenerationJob, GenerationResult, SceneCharacter)
before = tuple(session.scalar(select(func.count(m.id))) for m in MODELS)

# 1. all characters
report_all = character_consistency_report(session)
required = {"character", "summary", "findings", "affected_scenes", "affected_shots"}
assert required <= set(report_all), required - set(report_all)
for key in ("characters_scanned", "blockers", "warnings", "info", "missing_references",
            "missing_rules", "affected_scenes", "affected_shots"):
    assert key in report_all["summary"], key
for f in report_all["findings"]:
    assert {"severity", "type", "character_id", "episode_id", "scene_id", "shot_id",
            "message", "reason", "route", "action"} <= set(f), f
check("1. all characters: structured", report_all["summary"]["characters_scanned"] == 5,
      str(report_all["summary"]))
check("1. no fake metrics", "%" not in str(report_all["summary"])
      and "confidence_score" not in str(report_all).lower()
      and "estimated_time" not in str(report_all).lower()
      and "credits" not in str(report_all["summary"]).lower())

# 5. missing approved reference detection (sandbox has none)
check("5. missing refs detected", report_all["summary"]["missing_references"] == 5)

# 6. never-changes rules exist for canon characters (not flagged missing)
yeti = session.scalars(select(Character).where(Character.char_ref == "CHAR-YETI")).one()
never_missing = [f for f in report_all["findings"]
                 if f["character_id"] == yeti.id and f["type"] == "missing_never_changes"]
check("6. never_changes present -> not flagged", len(never_missing) == 0)

# 2. one character
report_one = character_consistency_report(session, character_id=yeti.id)
check("2. single character", report_one["summary"]["characters_scanned"] == 1
      and report_one["character"]["name"] == "Yeti")

# 3. episode filter
episode_id = session.scalar(select(Episode.id))
report_ep = character_consistency_report(session, episode_id=episode_id)
check("3. episode filter runs", report_ep["summary"]["characters_scanned"] == 5)
for f in report_ep["findings"]:
    assert f["episode_id"] in (None, episode_id), f

# 4. scene filter
scene_id = session.scalar(select(Scene.id))
report_sc = character_consistency_report(session, scene_id=scene_id)
check("4. scene filter runs", report_sc["summary"]["characters_scanned"] >= 1)

# 7. barefoot rule detection (inject a contradiction)
yeti.current_outfit = "Yeti wears red boots and a scarf"
session.commit()
report_bf = character_consistency_report(session, character_id=yeti.id)
barefoot = [f for f in report_bf["findings"] if f["type"] == "barefoot_canon"]
check("7. barefoot canon violation detected as blocker",
      len(barefoot) == 1 and barefoot[0]["severity"] == "blocker")
yeti.current_outfit = "All clothing and accessory details must come from creator artwork."
session.commit()
report_clean = character_consistency_report(session, character_id=yeti.id)
check("7b. clean outfit -> no barefoot finding",
      not any(f["type"] == "barefoot_canon" for f in report_clean["findings"]))

# 8. affected scenes/shots (Yeti is cast in 6 scenes from seed)
report_yeti = character_consistency_report(session, character_id=yeti.id)
check("8. affected scenes populated", report_yeti["summary"]["affected_scenes"] >= 1,
      str(report_yeti["summary"]["affected_scenes"]))
check("8b. affected_scenes list sorted",
      report_yeti["affected_scenes"] == sorted(report_yeti["affected_scenes"]))

# 9. deterministic ordering
r1 = character_consistency_report(session)
r2 = character_consistency_report(session)
check("9. deterministic output",
      [f["message"] for f in r1["findings"]] == [f["message"] for f in r2["findings"]])

# 10. deduplication (no identical severity+type+character+scene+shot+message)
keys = [(f["severity"], f["type"], f["character_id"], f["scene_id"], f["shot_id"], f["message"])
        for f in r1["findings"]]
check("10. no duplicate findings", len(keys) == len(set(keys)))

# 11. read-only proof
after = tuple(session.scalar(select(func.count(m.id))) for m in MODELS)
check("11. read-only (row counts)", before == after, f"{before} -> {after}")

# 12. invalid ids raise cleanly
for bad in [("character_id", 99999), ("episode_id", 99999), ("scene_id", 99999)]:
    try:
        character_consistency_report(session, **{bad[0]: bad[1]})
        check(f"12. invalid {bad[0]} rejected", False)
    except ValueError:
        check(f"12. invalid {bad[0]} rejected", True)

# severity sanity: blockers rare, warnings common, no all-blocker inflation
check("severity sanity", report_all["summary"]["blockers"] == 0
      and report_all["summary"]["warnings"] > 0,
      f"b={report_all['summary']['blockers']} w={report_all['summary']['warnings']}")

session.close()

# 13-14. no jobs created / statuses changed (via API surface too)
os.environ["STUDIO_TEST_PROVIDER"] = "1"
with TestClient(app) as c:
    s2 = SessionLocal()
    jobs_before = s2.scalar(select(func.count(GenerationJob.id)))
    statuses_before = {c.id: c.life_status for c in s2.scalars(select(Character)).all()}
    s2.close()
    r = c.get("/api/production/character-consistency")  # endpoint added? fallback: direct call check
    # direct service call through TestClient lifespan DB is shared; verify via service
    s2 = SessionLocal()
    character_consistency_report(s2)
    jobs_after = s2.scalar(select(func.count(GenerationJob.id)))
    statuses_after = {c.id: c.life_status for c in s2.scalars(select(Character)).all()}
    s2.close()
    check("13. no jobs created", jobs_before == jobs_after)
    check("14. no statuses changed", statuses_before == statuses_after)

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
