"""Agent API endpoints for cloud-connected mode (AGENT_MODE=1)."""
from __future__ import annotations

import asyncio
import datetime as dt
import hmac
import json
import logging
import time

import sqlalchemy as sa
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import rate_limited
from app.api.types import AgentHeartbeatIn, AgentIncidentIn, normalize_severity
from app.config import get_settings
from app.db.engine import get_engine
from app.db.tables import incidents
from app.ingestion.health import store_heartbeat
from app.redis_client import ALERT_CHANNEL, FRAME_CHANNEL, get_redis
from app.security import decrypt_source
from app.storage import presigned_put_url, snapshot_key
from app.storage import snapshot_url as resolve_snapshot_url

log = logging.getLogger(__name__)

router = APIRouter(prefix="/agent/v1", tags=["agent"])

# Rate limit for the /agent/v1 HTTP endpoints (DEMO-FR-27). The cap is generous
# enough for the normal heartbeat (30 s) + config poll (15 s) cadence plus
# incident bursts, and still stops a runaway/misbehaving agent. It is attached
# per endpoint rather than at the router, because a router-level dependency
# would also run on the /stream WebSocket, which has no Request.
_agent_rate_limit = Depends(rate_limited("agent", limit=600, window_secs=60))

# Message kinds an agent can put on the live stream socket.
FRAME = "frame"
PING = "ping"
PONG = "pong"
INVALID = "invalid"
OVERSIZE = "oversize"


def parse_agent_message(raw: str, max_bytes: int) -> tuple[str, dict | None]:
    """Classify one inbound agent stream message.

    Oversized messages are dropped before parsing (DEMO-FR: cloud drops any
    message > 1 MB). Only frame/count payloads are republished; ping/pong are
    handled by the socket itself.
    """
    if len(raw.encode("utf-8", "ignore")) > max_bytes:
        return OVERSIZE, None
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return INVALID, None
    if not isinstance(msg, dict):
        return INVALID, None
    mtype = msg.get("type")
    if mtype in (PING, PONG):
        return mtype, msg
    return FRAME, msg


async def _ws_ping(websocket: WebSocket, interval: float, send_lock: asyncio.Lock) -> None:
    try:
        while True:
            await asyncio.sleep(interval)
            async with send_lock:
                await websocket.send_text(json.dumps({"type": PING}))
    except (WebSocketDisconnect, RuntimeError):
        pass


def _require_agent_auth(request: Request) -> None:
    settings = get_settings()
    if not settings.agent_mode:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="agent mode disabled")
    token = request.headers.get("authorization") or request.headers.get("x-agent-token") or ""
    if token.startswith("Bearer "):
        token = token.split(" ", 1)[1]
    if not token or not settings.agent_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing agent token")
    if not hmac.compare_digest(token, settings.agent_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid agent token")


@router.get("/config", dependencies=[_agent_rate_limit])
async def get_config(request: Request):
    _require_agent_auth(request)
    # Return camera configs - reuse existing cameras logic
    from sqlalchemy import select

    from app.db.tables import cameras as cameras_table, upload_jobs

    engine = get_engine()
    async with engine.connect() as conn:
        # Uploaded files belong to the cloud worker's shared media volume.
        query = select(cameras_table).where(
            cameras_table.c.type != "youtube",
            ~select(upload_jobs.c.id).where(
                upload_jobs.c.camera_id == cameras_table.c.id
            ).exists()
        ).order_by(cameras_table.c.created_at)
        rows = (await conn.execute(query)).mappings().all()
        cameras = []
        for r in rows:
            cameras.append({
                "id": r["id"],
                "name": r["name"],
                # The agent must open the stream, so it gets the decrypted source
                # over the authenticated agent channel (TLS in production).
                "source": decrypt_source(r["source"]),
                "type": r["type"],
                "vertical_profile": r["vertical_profile"],
                "analysis_config": r.get("analysis_config") or {},
                "zones": r["zones"] or [],
                "rules": r["rules"] or [],
                "refresh_secs": r["refresh_secs"],
                "loop_file": r["loop_file"],
                "enabled": r["enabled"],
            })
        # Compute config version from cameras count + max updated? or simple hash
        import hashlib
        config_str = json.dumps(cameras, sort_keys=True)
        config_version = hashlib.md5(config_str.encode()).hexdigest()[:8]
        return {"config_version": config_version, "cameras": cameras}


async def _publish_incident_alert(
    incident_id: int,
    incident_uuid: str,
    camera_id: str,
    incident_type: str,
    severity: str,
    description: str | None,
    snapshot_path: str | None,
    ts: dt.datetime,
) -> None:
    """Publish the existing alert payload shape so ws/manager.py and the
    dashboard work unchanged (DEMO-FR-21/22)."""
    alert = {
        "type": "incident",
        "id": incident_id,
        "uuid": incident_uuid,
        "camera_id": camera_id,
        "incident_type": incident_type,
        "severity": severity,
        "description": description,
        "snapshot_url": resolve_snapshot_url(snapshot_path),
        "ts": ts.isoformat(),
    }
    await get_redis().publish(ALERT_CHANNEL, json.dumps(alert))


@router.post("/incidents", dependencies=[_agent_rate_limit])
async def post_incidents(request: Request, payload: AgentIncidentIn) -> dict:
    """Upsert an agent incident by UUID, mint a presigned PUT, fan out the alert.

    Idempotent: the same UUID twice returns ``duplicate=true`` and never creates
    a second row (PRD v2 Phase 1a DEMO-FR-21).
    """
    _require_agent_auth(request)

    incident_uuid = str(payload.uuid)
    ts_value = payload.ts if payload.ts is not None else time.time()
    ts = dt.datetime.fromtimestamp(ts_value, tz=dt.UTC)
    severity = normalize_severity(payload.severity)
    details = payload.details if isinstance(payload.details, dict) else {}
    description = details.get("description")
    snapshot_path = snapshot_key(incident_uuid, ts) if payload.has_snapshot else None

    engine = get_engine()
    duplicate = False
    async with engine.begin() as conn:
        inserted = await conn.execute(
            pg_insert(incidents)
            .values(
                uuid=payload.uuid,
                camera_id=payload.camera_id,
                ts=ts,
                incident_type=payload.type,
                severity=severity,
                description=description,
                snapshot_path=snapshot_path,
                status="open",
            )
            .on_conflict_do_nothing(index_elements=["uuid"])
            .returning(incidents.c.id)
        )
        row = inserted.first()
        if row is not None:
            incident_id = row[0]
        else:
            duplicate = True
            existing = (
                await conn.execute(
                    sa.select(incidents.c.id, incidents.c.snapshot_path).where(
                        incidents.c.uuid == payload.uuid
                    )
                )
            ).mappings().one()
            incident_id = existing["id"]
            # Preserve the original snapshot key when the retry omits a snapshot.
            snapshot_path = snapshot_path or existing["snapshot_path"]

    if not duplicate:
        await _publish_incident_alert(
            incident_id,
            incident_uuid,
            payload.camera_id,
            payload.type,
            severity,
            description,
            snapshot_path,
            ts,
        )
        log.info(
            "agent incident stored",
            extra={"camera_id": payload.camera_id, "incident_id": incident_id},
        )

    return {
        "incident_id": incident_id,
        "snapshot_put_url": presigned_put_url(snapshot_path) if snapshot_path else None,
        "duplicate": duplicate,
    }


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT,
             dependencies=[_agent_rate_limit])
async def post_heartbeat(request: Request, payload: AgentHeartbeatIn) -> Response:
    """Record agent liveness and per-camera health (PRD v2 Phase 1a §5)."""
    _require_agent_auth(request)
    await store_heartbeat(payload.model_dump())
    log.debug(
        "agent heartbeat",
        extra={"cameras": len(payload.cameras), "uptime_s": payload.uptime_s},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _require_agent_ws_auth(websocket: WebSocket) -> bool:
    token = websocket.query_params.get("token")
    if not token:
        auth = websocket.headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            token = auth.split(" ", 1)[1]
    settings = get_settings()
    return bool(
        settings.agent_mode
        and token
        and settings.agent_token
        and hmac.compare_digest(token, settings.agent_token)
    )


@router.websocket("/stream")
async def ws_stream(websocket: WebSocket):
    """Live frame uplink from a site agent.

    Frames arrive as the same JSON payload the local pipeline already publishes
    on ``FRAME_CHANNEL``; the cloud republishes them verbatim so the existing
    ws/manager fan-out and dashboard render unchanged (DEMO-FR-24/40).
    """
    if not _require_agent_ws_auth(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()

    settings = get_settings()
    send_lock = asyncio.Lock()
    ping_task = asyncio.create_task(
        _ws_ping(websocket, settings.agent_ws_ping_seconds, send_lock)
    )
    try:
        await websocket.send_text(json.dumps({"type": "hello"}))
        while True:
            raw = await websocket.receive_text()
            kind, msg = parse_agent_message(raw, settings.agent_max_message_bytes)
            if kind == OVERSIZE:
                log.warning("dropped oversized agent stream message")
                continue
            if kind == INVALID:
                continue
            if kind == PING:
                async with send_lock:
                    await websocket.send_text(json.dumps({"type": PONG}))
                continue
            if kind == PONG:
                continue
            await get_redis().publish(FRAME_CHANNEL, raw)
    except WebSocketDisconnect:
        pass
    finally:
        ping_task.cancel()
