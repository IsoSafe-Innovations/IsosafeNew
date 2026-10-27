"""Cloud-side agent liveness watchdog (PRD v2 Phase 1a DEMO-FR-26).

Runs in the cloud API process. When the site agent's heartbeat goes stale
(``last_seen`` older than ``AGENT_ONLINE_SECS``, default 90 s) it raises a single
``agent_offline`` incident; when the agent reconnects it resolves that incident.
Only one *open* ``agent_offline`` incident exists at a time, so repeated ticks
never duplicate it.

The API runs behind multiple gunicorn workers, each of which starts this loop;
a short-lived Redis lock elects exactly one worker per interval so the incident
is created/resolved once.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time
import uuid

import sqlalchemy as sa

from app.config import get_settings
from app.db.engine import get_engine
from app.db.tables import incidents
from app.ingestion.health import read_agent_health
from app.redis_client import ALERT_CHANNEL, get_redis

log = logging.getLogger(__name__)

WATCHDOG_INTERVAL = 15.0
LOCK_KEY = "isosafe:agent_watchdog:lock"

AGENT_CAMERA_ID = "agent"
AGENT_OFFLINE_TYPE = "agent_offline"
AGENT_OFFLINE_SEVERITY = "critical"
OPEN_STATUSES = ("open", "investigating")
OFFLINE_DESCRIPTION = "Site agent heartbeat is stale; no local monitoring is reporting."


def _publish_alert(
    incident_uuid: uuid.UUID | None,
    incident_id: int,
    ts: dt.datetime,
    status: str,
) -> None:
    """Publish the standard incident alert so live dashboards update."""
    alert = {
        "type": "incident",
        "id": incident_id,
        "uuid": str(incident_uuid) if incident_uuid else None,
        "camera_id": AGENT_CAMERA_ID,
        "incident_type": AGENT_OFFLINE_TYPE,
        "severity": AGENT_OFFLINE_SEVERITY,
        "description": OFFLINE_DESCRIPTION,
        "snapshot_url": None,
        "status": status,
        "ts": ts.isoformat(),
    }
    return get_redis().publish(ALERT_CHANNEL, json.dumps(alert))


async def open_offline_incident() -> bool:
    """Create the ``agent_offline`` incident unless one is already open."""
    engine = get_engine()
    now = dt.datetime.now(dt.UTC)
    incident_uuid = uuid.uuid4()
    async with engine.begin() as conn:
        existing = (
            await conn.execute(
                sa.select(incidents.c.id)
                .where(
                    incidents.c.incident_type == AGENT_OFFLINE_TYPE,
                    incidents.c.status.in_(OPEN_STATUSES),
                )
                .limit(1)
            )
        ).first()
        if existing is not None:
            return False
        incident_id = (
            await conn.execute(
                sa.insert(incidents)
                .values(
                    uuid=incident_uuid,
                    camera_id=AGENT_CAMERA_ID,
                    ts=now,
                    incident_type=AGENT_OFFLINE_TYPE,
                    severity=AGENT_OFFLINE_SEVERITY,
                    description=OFFLINE_DESCRIPTION,
                    status="open",
                )
                .returning(incidents.c.id)
            )
        ).scalar_one()
    await _publish_alert(incident_uuid, incident_id, now, "open")
    log.warning("agent_offline incident created id=%s", incident_id)
    return True


async def resolve_offline_incidents() -> int:
    """Resolve any open ``agent_offline`` incidents; returns how many."""
    engine = get_engine()
    now = dt.datetime.now(dt.UTC)
    async with engine.begin() as conn:
        rows = (
            await conn.execute(
                sa.update(incidents)
                .where(
                    incidents.c.incident_type == AGENT_OFFLINE_TYPE,
                    incidents.c.status.in_(OPEN_STATUSES),
                )
                .values(status="resolved", resolved_at=now)
                .returning(incidents.c.id, incidents.c.uuid, incidents.c.ts)
            )
        ).all()
    for incident_id, incident_uuid, ts in rows:
        await _publish_alert(incident_uuid, incident_id, ts, "resolved")
    if rows:
        log.info("agent_offline incident(s) resolved: %s", [r[0] for r in rows])
    return len(rows)


async def _tick() -> None:
    """One watchdog pass: create on stale heartbeat, resolve on recovery."""
    health = await read_agent_health()
    age = health.get("last_seen_ago")
    if age is None:
        # The agent has never checked in; nothing to alert on yet.
        return
    if age > get_settings().agent_online_secs:
        await open_offline_incident()
    else:
        await resolve_offline_incidents()


async def run_agent_watchdog(stop_event: asyncio.Event) -> None:
    r = get_redis()
    lock_ttl_ms = int(WATCHDOG_INTERVAL * 1000)
    while not stop_event.is_set():
        try:
            # Elect one worker per interval (the lock outlives the tick by design).
            if await r.set(LOCK_KEY, str(time.time()), nx=True, px=lock_ttl_ms):
                await _tick()
        except Exception:
            log.exception("agent watchdog tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=WATCHDOG_INTERVAL)
        except TimeoutError:
            pass
