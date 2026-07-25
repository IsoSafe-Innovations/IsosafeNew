import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, require_admin, require_viewer, write_audit
from app.config import get_settings
from app.db.engine import get_engine
from app.db.tables import cameras
from app.ingestion.health import read_all_health
from app.ingestion.onvif_discovery import discover_cameras, get_stream_uri
from app.profiles.registry import apply_profile, list_profiles
from app.security import encrypt_source, redact_source

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

SOURCE_TYPES = {"rtsp", "snapshot_url", "file"}


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


def _serialize(row: dict, health: dict | None = None) -> dict:
    out = dict(row)
    out["source"] = redact_source(row["source"])
    out["created_at"] = row["created_at"].isoformat() if row["created_at"] else None
    if health is not None:
        out["health"] = health
    return out


@router.get("")
async def list_cameras(user: CurrentUser = Depends(require_viewer)) -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        rows = (await conn.execute(sa.select(cameras))).mappings().all()
    health = await read_all_health([r["id"] for r in rows])
    return [_serialize(r, health.get(r["id"])) for r in rows]


@router.post("", status_code=201)
async def add_camera(body: CameraCreate, user: CurrentUser = Depends(require_admin)) -> dict:
    if body.type not in SOURCE_TYPES:
        raise HTTPException(status_code=422, detail=f"type must be one of {sorted(SOURCE_TYPES)}")
    engine = get_engine()
    async with engine.connect() as conn:
        count = (await conn.execute(sa.select(sa.func.count()).select_from(cameras))).scalar_one()
    if count >= get_settings().max_cameras_per_node:
        raise HTTPException(status_code=409, detail="MAX_CAMERAS_PER_NODE reached")

    camera_id = f"cam-{uuid.uuid4().hex[:8]}"
    zones, rules = body.zones, body.rules
    if body.vertical_profile and not rules:
        zones, rules = apply_profile(body.vertical_profile, zones)

    async with engine.begin() as conn:
        await conn.execute(
            sa.insert(cameras).values(
                id=camera_id,
                name=body.name,
                source=encrypt_source(body.source),
                type=body.type,
                vertical_profile=body.vertical_profile,
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
    if "type" in updates and updates["type"] not in SOURCE_TYPES:
        raise HTTPException(status_code=422, detail=f"type must be one of {sorted(SOURCE_TYPES)}")
    if "source" in updates:
        updates["source"] = encrypt_source(updates["source"])
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    engine = get_engine()
    async with engine.begin() as conn:
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
        result = await conn.execute(sa.delete(cameras).where(cameras.c.id == camera_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Camera not found")
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
