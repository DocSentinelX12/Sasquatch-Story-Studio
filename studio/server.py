"""FastAPI application assembly for Sasquatch Story Studio.

Run from the repository root:

    .venv/bin/uvicorn studio.server:app --host 0.0.0.0 --port 8000

or simply:  ./run.sh
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import assets, batch, characters, dashboard, episodes, generation, phase8, phase9, phase10, postproduction, projects, shots, story, system, world
from .config import settings
from .db import SessionLocal, create_all
from .services.generation_service import resume_pending_jobs
from .services.seed import backfill_canon_fields, refresh_provider_status, seed_if_empty, seed_story_layer


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    session = SessionLocal()
    try:
        seed_if_empty(session)          # idempotent import of canon content
        seed_story_layer(session)       # Phase 3: bible fields, canon, casting, script
        backfill_canon_fields(session)  # Phase 2 fields for Phase 1 databases
        from .services.automation import seed_default_rules
        from sqlalchemy import select as _sel
        from .models import Project as _P
        for _proj in session.scalars(_sel(_P)).all():
            seed_default_rules(session, _proj.id)
        refresh_provider_status(session)
    finally:
        session.close()
    try:
        from .db import SessionLocal as _SL
        from .api.phase9 import auto_backup_due
        from .services.backup import write_auto_backup
        _s = _SL()
        try:
            if auto_backup_due(_s):
                from sqlalchemy import select as _sel
                from .models import Project as _P
                for _proj in _s.scalars(_sel(_P)).all():
                    write_auto_backup(_s, _proj.id, "auto")
                print("[studio] automatic backup written")
        finally:
            _s.close()
    except Exception as _e:  # noqa: BLE001
        print(f"[studio] auto-backup skipped: {_e}")
    try:
        resumed = resume_pending_jobs()
        if resumed:
            print(f"[studio] resumed polling for {resumed} in-flight generation job(s)")
    except Exception as error:  # noqa: BLE001 - never block boot on resume
        print(f"[studio] generation resume skipped: {error}")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sasquatch Story Studio",
        version=settings.app_version,
        description=(
            "Production hub for the Sasquatch animated series: story → episode → "
            "scene → shot → references → generation → export. Approval-first; "
            "creator artwork is the visual source of truth."
        ),
        lifespan=lifespan,
    )

    app.include_router(dashboard.router)
    app.include_router(projects.router)
    app.include_router(episodes.router)
    app.include_router(story.router)
    app.include_router(world.router)
    app.include_router(characters.router)
    app.include_router(assets.router)
    app.include_router(shots.router)
    app.include_router(postproduction.router)
    app.include_router(batch.router)
    app.include_router(phase8.router)
    app.include_router(phase9.router)
    app.include_router(phase10.router)
    app.include_router(generation.router)
    app.include_router(system.router)

    # Static SPA (hash routing — no server-side fallback needed).
    if settings.web_root.is_dir():
        app.mount("/", StaticFiles(directory=str(settings.web_root), html=True), name="web")
    return app


app = create_app()
