"""System endpoints: app info, environment status (names only), content validation."""

from __future__ import annotations

import subprocess
import sys

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import env, settings
from ..models import Base
from ..providers.registry import DEFINITIONS
from ..services.seed import refresh_provider_status, seed_if_empty
from .deps import get_db

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/info")
def app_info(db: Session = Depends(get_db)):
    table_counts = {
        name: db.scalar(select(func.count()).select_from(table))
        for name, table in sorted(Base.metadata.tables.items())
    }
    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "repo_root": str(settings.repo_root),
        "database_path": str(settings.database_absolute),
        "upload_root": str(settings.upload_root),
        "table_counts": table_counts,
        "notes": [
            "Provider credentials live only in server-side environment variables.",
            "The JSON content system (series-bible/, assets/, episodes/) remains the canon source of truth.",
        ],
    }


@router.get("/env-status")
def env_status():
    """Which provider credential variables are set. NAMES only — never values."""
    report = {}
    for definition in DEFINITIONS.values():
        report[definition.key] = {
            "required_env": {name: {"set": env(name) is not None} for name in definition.required_env},
            "optional_env": {name: {"set": env(name) is not None} for name in definition.optional_env},
        }
    return {"env_status": report}


@router.post("/validate-content")
def validate_content():
    """Run the repository's canon validator (tools/validate_content.py)."""
    script = settings.repo_root / "tools" / "validate_content.py"
    if not script.is_file():
        raise HTTPException(404, "tools/validate_content.py not found")
    try:
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(settings.repo_root),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Validator timed out")
    return {
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "output": completed.stdout.strip()[-8000:],
        "errors": completed.stderr.strip()[-4000:],
    }


@router.post("/seed")
def seed(db: Session = Depends(get_db)):
    """Idempotent import of the content repository into the database."""
    result = seed_if_empty(db)
    refreshed = refresh_provider_status(db)
    return {"seed": result, "providers_refreshed": refreshed}


@router.get("/health")
def health():
    return {"status": "ok"}
