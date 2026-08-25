"""Asset library endpoints: upload, browse, search, filter, version, approve."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Approval,
    Asset,
    AssetCategory,
    AssetClass,
    AssetProvenance,
    AssetStatus,
    AssetStorageMode,
    AssetTag,
    AssetVersion,
    CharacterReference,
)
from ..services.scanner import register_repo_assets
from ..services.storage import resolve_repo_path, store_upload
from .deps import get_db, row_to_dict

router = APIRouter(prefix="/api/assets", tags=["assets"])

CATEGORIES = {c.value for c in AssetCategory}
ASSET_STATUSES = {s.value for s in AssetStatus}
ASSET_CLASSES = {c.value for c in AssetClass}
PROVENANCES = {p.value for p in AssetProvenance}

# UI vocabulary aliases (Phase 2 approval workflow wording) → stored values.
STATUS_ALIASES = {
    "draft": "registered",
    "review": "pending_approval",
    "in_review": "pending_approval",
    "archived": "obsolete",
}
SORTS = {
    "newest": Asset.id.desc(),
    "oldest": Asset.id.asc(),
    "title": Asset.title.asc(),
    "size": Asset.byte_size.desc().nullslast(),
}


def normalize_status(value: str) -> str:
    return STATUS_ALIASES.get(value, value)


def sync_asset_tags(db: Session, asset: Asset) -> None:
    """Keep the asset_tags index table in sync with asset.tags JSON."""
    wanted = sorted({(tag or "").strip().lower() for tag in (asset.tags or []) if (tag or "").strip()})
    for name in wanted:
        existing = db.scalar(
            select(AssetTag).where(
                AssetTag.project_id == asset.project_id,
                AssetTag.name == name,
            )
        )
        if existing is None:
            db.add(AssetTag(project_id=asset.project_id, name=name))


class AssetStatusUpdate(BaseModel):
    # Accepts stored vocabulary (registered/pending_approval/approved/rejected/obsolete)
    # and UI aliases (draft/review/in_review/archived).
    status: str = Field(pattern="^(registered|pending_approval|approved|rejected|obsolete|draft|review|in_review|archived)$")
    note: Optional[str] = None


class VersionStatusUpdate(BaseModel):
    status: str = Field(pattern="^(registered|pending_approval|approved|rejected|obsolete|draft|review|in_review|archived)$")
    note: Optional[str] = None


class AssetMetaUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    category: Optional[str] = None
    character_id: Optional[int] = None
    location_id: Optional[int] = None
    episode_id: Optional[int] = None
    provenance: Optional[str] = None


def _validate_choice(value: str | None, allowed: set[str], label: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(422, f"{label} must be one of {sorted(allowed)}")


@router.get("")
def list_assets(
    q: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    asset_class: Optional[str] = None,
    provenance: Optional[str] = None,
    favorite: Optional[bool] = None,
    project_id: Optional[int] = None,
    character_id: Optional[int] = None,
    episode_id: Optional[int] = None,
    tag: Optional[str] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    sort: str = "newest",
    limit: int = 60,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    _validate_choice(category, CATEGORIES, "category")
    _validate_choice(asset_class, ASSET_CLASSES, "asset_class")
    _validate_choice(provenance, PROVENANCES, "provenance")
    normalized_status = normalize_status(status) if status else None
    if normalized_status is not None and normalized_status not in ASSET_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(ASSET_STATUSES)} (or alias draft/review/archived)")
    if sort not in SORTS:
        raise HTTPException(422, f"sort must be one of {sorted(SORTS)}")

    query = select(Asset)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(
            or_(
                func.lower(Asset.title).like(like),
                func.lower(Asset.original_filename).like(like),
                func.lower(Asset.repo_path).like(like),
                func.lower(Asset.notes).like(like),
            )
        )
    for column, value in (
        (Asset.category, category),
        (Asset.status, normalized_status),
        (Asset.asset_class, asset_class),
        (Asset.provenance, provenance),
        (Asset.project_id, project_id),
        (Asset.character_id, character_id),
        (Asset.episode_id, episode_id),
    ):
        if value is not None:
            query = query.where(column == value)
    if favorite is not None:
        query = query.where(Asset.is_favorite == favorite)
    if tag:
        # JSON-array containment via serialized LIKE (SQLite cannot correlate
        # json_each() inside EXISTS; quoted match avoids partial hits).
        needle = tag.lower().replace('"', "").replace("%", "")
        query = query.where(cast(Asset.tags, String).like(f'%"{needle}"%'))
    if created_after:
        query = query.where(Asset.created_at >= created_after)
    if created_before:
        before = created_before + " 23:59:59" if len(created_before) == 10 else created_before
        query = query.where(Asset.created_at <= before)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(SORTS[sort]).offset(offset).limit(min(limit, 200))
    ).all()

    counts = dict(
        db.execute(
            select(Asset.category, func.count(Asset.id)).group_by(Asset.category)
        ).all()
    )
    status_counts = dict(
        db.execute(select(Asset.status, func.count(Asset.id)).group_by(Asset.status)).all()
    )
    return {
        "assets": [row_to_dict(a) for a in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "counts_by_category": counts,
        "counts_by_status": status_counts,
    }


@router.get("/tags")
def list_tags(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Tag cloud with usage counts (json_each join over all assets)."""
    from sqlalchemy import text

    rows = db.execute(
        text(
            "SELECT lower(je.value) AS name, count(*) AS cnt "
            "FROM assets a, json_each(a.tags) je "
            "WHERE (:project_id IS NULL OR a.project_id = :project_id) "
            "GROUP BY lower(je.value) ORDER BY cnt DESC, name ASC"
        ),
        {"project_id": project_id},
    ).all()
    tags = [{"name": name, "count": count} for name, count in rows if name]
    return {"tags": tags}


@router.post("/upload", status_code=201)
async def upload_asset(
    file: UploadFile = File(...),
    category: str = Form("other"),
    title: Optional[str] = Form(None),
    provenance: str = Form("meta_ai"),
    tags: str = Form(""),
    notes: str = Form(""),
    project_id: Optional[int] = Form(None),
    character_id: Optional[int] = Form(None),
    location_id: Optional[int] = Form(None),
    episode_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """Import an externally generated file (e.g. Meta AI artwork) as an asset.

    The file is stored under app-managed storage; existing repository files are
    never touched. New assets start as pending_approval (approval-first).
    """
    _validate_choice(category, CATEGORIES, "category")
    _validate_choice(provenance, PROVENANCES, "provenance")
    content = await file.read()
    if not content:
        raise HTTPException(422, "Uploaded file is empty")
    try:
        stored = store_upload(content, file.filename or "upload", category)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    version = AssetVersion(
        version_number=1,
        storage_mode=AssetStorageMode.UPLOAD.value,
        repo_path=stored.repo_path,
        sha256=stored.sha256,
        byte_size=stored.byte_size,
        mime_type=stored.mime_type,
        source="upload",
        is_current=True,
        status="registered",  # draft — never auto-approved
    )
    asset = Asset(
        project_id=project_id,
        category=category,
        title=title or (file.filename or "Untitled"),
        original_filename=file.filename,
        storage_mode=AssetStorageMode.UPLOAD.value,
        repo_path=stored.repo_path,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        sha256=stored.sha256,
        asset_class=AssetClass.AI_GENERATED_TEST_MATERIAL.value
        if provenance in ("meta_ai", "provider")
        else AssetClass.UNCLASSIFIED.value,
        provenance=provenance,
        status=AssetStatus.REGISTERED.value,
        is_favorite=False,
        tags=tag_list,
        notes=notes or None,
        character_id=character_id,
        location_id=location_id,
        episode_id=episode_id,
        versions=[version],
    )
    db.add(asset)
    db.flush()
    asset.current_version_id = version.id
    sync_asset_tags(db, asset)
    db.commit()
    db.refresh(asset)
    return row_to_dict(asset)


@router.post("/scan-repo")
def scan_repository(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Register existing repository media in place (read-only on disk)."""
    report = register_repo_assets(db, project_id=project_id)
    return report.as_dict()


@router.get("/{asset_id}")
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    versions = db.scalars(
        select(AssetVersion).where(AssetVersion.asset_id == asset_id).order_by(AssetVersion.version_number.desc())
    ).all()
    return {**row_to_dict(asset), "versions": [row_to_dict(v) for v in versions]}


@router.get("/{asset_id}/file")
def get_asset_file(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if asset is None or not asset.repo_path:
        raise HTTPException(404, "File not available")
    path = resolve_repo_path(asset.repo_path)
    if path is None:
        raise HTTPException(404, "File missing on disk")
    return FileResponse(path, media_type=asset.mime_type or "application/octet-stream")


@router.patch("/{asset_id}")
def update_asset_meta(asset_id: int, payload: AssetMetaUpdate, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    _validate_choice(payload.category, CATEGORIES, "category")
    _validate_choice(payload.provenance, PROVENANCES, "provenance")
    updates = payload.model_dump(exclude_none=True)
    for field, value in updates.items():
        setattr(asset, field, value)
    if "tags" in updates:
        sync_asset_tags(db, asset)
    db.commit()
    db.refresh(asset)
    return row_to_dict(asset)


@router.post("/{asset_id}/status")
def set_asset_status(asset_id: int, payload: AssetStatusUpdate, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    normalized = normalize_status(payload.status)
    previous = asset.status
    asset.status = normalized
    decision = {
        "approved": "approved",
        "rejected": "rejected",
        "obsolete": "changes_requested",
    }.get(normalized, "changes_requested")
    db.add(Approval(
        entity_type="asset",
        entity_id=str(asset_id),
        decision=decision,
        note=payload.note or f"status: {previous} → {normalized}",
    ))
    db.commit()
    db.refresh(asset)
    return row_to_dict(asset)


@router.post("/{asset_id}/favorite")
def toggle_favorite(asset_id: int, db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    asset.is_favorite = not asset.is_favorite
    db.commit()
    db.refresh(asset)
    return row_to_dict(asset)


@router.post("/{asset_id}/versions", status_code=201)
async def add_asset_version(
    asset_id: int,
    file: UploadFile = File(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """Add a new version of an asset. Existing versions are never deleted."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    content = await file.read()
    if not content:
        raise HTTPException(422, "Uploaded file is empty")
    try:
        stored = store_upload(content, file.filename or "version", asset.category)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    last = db.scalar(
        select(func.max(AssetVersion.version_number)).where(AssetVersion.asset_id == asset_id)
    ) or 0
    db.execute(
        AssetVersion.__table__.update()
        .where(AssetVersion.asset_id == asset_id)
        .values(is_current=False)
    )
    version = AssetVersion(
        asset_id=asset_id,
        version_number=last + 1,
        storage_mode=AssetStorageMode.UPLOAD.value,
        repo_path=stored.repo_path,
        sha256=stored.sha256,
        byte_size=stored.byte_size,
        mime_type=stored.mime_type,
        source="replace",
        notes=notes or None,
        is_current=True,
        status="registered",  # new versions start as draft; previous versions are kept
    )
    db.add(version)
    db.flush()
    asset.current_version_id = version.id
    asset.repo_path = stored.repo_path
    asset.sha256 = stored.sha256
    asset.byte_size = stored.byte_size
    asset.mime_type = stored.mime_type
    asset.storage_mode = AssetStorageMode.UPLOAD.value
    db.commit()
    return {**row_to_dict(asset), "new_version": row_to_dict(version)}


@router.post("/{asset_id}/versions/{version_id}/status")
def set_version_status(asset_id: int, version_id: int, payload: VersionStatusUpdate, db: Session = Depends(get_db)):
    """Set a version's review state (draft / review / approved / rejected / archived)."""
    version = db.get(AssetVersion, version_id)
    if version is None or version.asset_id != asset_id:
        raise HTTPException(404, "Version not found")
    normalized = normalize_status(payload.status)
    version.status = normalized
    db.add(Approval(
        entity_type="asset_version",
        entity_id=str(version_id),
        decision="approved" if normalized == "approved" else "changes_requested",
        note=payload.note or f"version {version.version_number}: → {normalized}",
    ))
    db.commit()
    db.refresh(version)
    return row_to_dict(version)


@router.post("/{asset_id}/versions/{version_id}/current")
def set_current_version(asset_id: int, version_id: int, db: Session = Depends(get_db)):
    """Mark one version as Current. Other versions are demoted, never deleted."""
    asset = db.get(Asset, asset_id)
    version = db.get(AssetVersion, version_id)
    if asset is None or version is None or version.asset_id != asset_id:
        raise HTTPException(404, "Version not found")
    db.execute(
        AssetVersion.__table__.update()
        .where(AssetVersion.asset_id == asset_id)
        .values(is_current=False)
    )
    version.is_current = True
    asset.current_version_id = version.id
    asset.repo_path = version.repo_path
    asset.sha256 = version.sha256
    asset.byte_size = version.byte_size
    asset.mime_type = version.mime_type
    db.commit()
    db.refresh(version)
    db.refresh(asset)
    return {"asset": row_to_dict(asset), "version": row_to_dict(version)}
