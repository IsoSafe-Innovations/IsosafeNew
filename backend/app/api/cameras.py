import logging
import uuid
from pathlib import Path

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, require_admin, require_viewer, write_audit
from app.config import get_settings
from app.db.engine import get_engine
from app.db.tables import cameras, upload_jobs
from app.ingestion.health import read_all_health
from app.ingestion.youtube import canonical_url, video_id
from app.inference.options import AnalysisOptions
from app.inference.telemetry import read_analysis
from app.rules.validation import validate_rules
from app.ingestion.onvif_discovery import discover_cameras, get_stream_uri
from app.profiles.registry import apply_profile, list_profiles
from app.security import encrypt_source, redact_source

router = APIRouter(prefix="/api/cameras", tags=["cameras"])
log = logging.getLogger(__name__)

SOURCE_TYPES = {"rtsp", "snapshot_url", "file", "youtube"}


class CameraCreate(BaseModel):
    name: str
    source: str
    type: str
    vertical_profile: str | None = None
    zones: list[dict] = Field(default_factory=list)
    rules: list[dict] = Field(default_factory=list)
    refresh_secs: float = 2.0
    loop_file: bool = True
    enabled: bool = True
    analysis_config: AnalysisOptions = Field(default_factory=AnalysisOptions)


class CameraPatch(BaseModel):
    name: str | None = None
    source: str | None = None
    type: str | None = None
    vertical_profile: str | None = None
    zones: list[dict] | None = None
    rules: list[dict] | None = None
    refresh_secs: float | None = None
    loop_file: bool | None = None
    enabled: bool | None = None
    analysis_config: AnalysisOptions | None = None


def _serialize(row: dict, health: dict | None = None) -> dict:
    out = dict(row)
    out["source"] = redact_source(row["source"])
    if row["type"] == "youtube":
        out["youtube_id"] = video_id(out["source"])
    out["created_at"] = row["created_at"].isoformat() if row["created_at"] else None
    if health is not None:
        out["health"] = health
    return out


@router.get("")
async def list_cameras(user: CurrentUser = Depends(require_viewer)) -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        is_upload = sa.exists().where(upload_jobs.c.camera_id == cameras.c.id).label("is_upload")
        rows = (await conn.execute(sa.select(cameras, is_upload))).mappings().all()
    health = await read_all_health([r["id"] for r in rows])
    analysis = await read_analysis([r["id"] for r in rows])
    return [{**_serialize(r, health.get(r["id"])), "analysis": analysis.get(r["id"])} for r in rows]


@router.post("", status_code=201)
async def add_camera(body: CameraCreate, user: CurrentUser = Depends(require_admin)) -> dict:
    if body.type not in SOURCE_TYPES:
        raise HTTPException(status_code=422, detail=f"type must be one of {sorted(SOURCE_TYPES)}")
    if body.type == "youtube":
        try:
            body.source = canonical_url(body.source)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    engine = get_engine()
    camera_id = f"cam-{uuid.uuid4().hex[:8]}"
    zones, rules = body.zones, body.rules
    if body.vertical_profile and not rules:
        zones, rules = apply_profile(body.vertical_profile, zones)
    try:
        validate_rules(rules, zones)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    async with engine.begin() as conn:
        await conn.execute(sa.text("LOCK TABLE cameras IN SHARE ROW EXCLUSIVE MODE"))
        count = (await conn.execute(sa.select(sa.func.count()).select_from(cameras))).scalar_one()
        if count >= get_settings().max_cameras_per_node:
            raise HTTPException(status_code=409, detail="MAX_CAMERAS_PER_NODE reached")
        await conn.execute(
            sa.insert(cameras).values(
                id=camera_id,
                name=body.name,
                source=encrypt_source(body.source),
                type=body.type,
                vertical_profile=body.vertical_profile,
                analysis_config=body.analysis_config.model_dump(),
                zones=zones,
                rules=rules,
                refresh_secs=body.refresh_secs,
                loop_file=body.loop_file,
                enabled=body.enabled,
            )
        )
        row = (
            await conn.execute(sa.select(cameras).where(cameras.c.id == camera_id))
        ).mappings().one()
    await write_audit(user.email, "camera.create", camera_id, {"name": body.name})
    return _serialize(row)


@router.patch("/{camera_id}")
async def patch_camera(
    camera_id: str, body: CameraPatch, user: CurrentUser = Depends(require_admin)
) -> dict:
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if "analysis_config" in updates and updates["analysis_config"] is None:
        raise HTTPException(status_code=422, detail="Analysis settings cannot be null")
    if any(key in updates and updates[key] is None for key in ("rules", "zones")):
        raise HTTPException(status_code=422, detail="Rules and zones must be lists")
    if "type" in updates and updates["type"] not in SOURCE_TYPES:
        raise HTTPException(status_code=422, detail=f"type must be one of {sorted(SOURCE_TYPES)}")
    if "source" in updates:
        updates["source"] = encrypt_source(updates["source"])
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    engine = get_engine()
    async with engine.begin() as conn:
        if {"source", "type", "rules", "zones"} & updates.keys():
            current = (await conn.execute(sa.select(cameras).where(cameras.c.id == camera_id))).mappings().first()
            if current is None:
                raise HTTPException(status_code=404, detail="Camera not found")
            try:
                validate_rules(updates.get("rules", current["rules"]), updates.get("zones", current["zones"]))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if updates.get("type", current["type"]) == "youtube":
                from app.security import decrypt_source
                try:
                    updates["source"] = canonical_url(decrypt_source(updates.get("source", current["source"])))
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = await conn.execute(
            sa.update(cameras).where(cameras.c.id == camera_id).values(**updates)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Camera not found")
        row = (
            await conn.execute(sa.select(cameras).where(cameras.c.id == camera_id))
        ).mappings().one()
    await write_audit(user.email, "camera.update", camera_id,
                      {k: "***" if k == "source" else v for k, v in updates.items()})
    return _serialize(row)


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(camera_id: str, user: CurrentUser = Depends(require_admin)) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        uploads = (await conn.execute(
            sa.delete(upload_jobs).where(upload_jobs.c.camera_id == camera_id)
            .returning(upload_jobs.c.id, upload_jobs.c.filename)
        )).mappings().all()
        result = await conn.execute(sa.delete(cameras).where(cameras.c.id == camera_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Camera not found")
    for upload in uploads:
        # Derive only generated upload paths; never delete a caller-supplied source.
        ext = Path(upload["filename"]).suffix.lower()
        path = Path(get_settings().media_root) / "uploads" / f"{upload['id']}{ext}"
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.exception("could not remove video for deleted camera %s", camera_id)
    await write_audit(user.email, "camera.delete", camera_id)


@router.get("/profiles")
async def get_profiles(user: CurrentUser = Depends(require_viewer)) -> list[dict]:
    return list_profiles()


@router.post("/discover")
async def onvif_discover(user: CurrentUser = Depends(require_admin)) -> list[dict]:
    """Scan the local subnet for ONVIF devices. Returns candidates for approval."""
    return await discover_cameras()


class StreamUriRequest(BaseModel):
    host: str
    port: int = 80
    username: str = ""
    password: str = ""


@router.post("/discover/stream-uri")
async def onvif_stream_uri(
    body: StreamUriRequest, user: CurrentUser = Depends(require_admin)
) -> dict:
    uri = await get_stream_uri(body.host, body.port, body.username, body.password)
    if uri is None:
        raise HTTPException(status_code=502, detail="Could not retrieve stream URI")
    return {"stream_uri": uri}
