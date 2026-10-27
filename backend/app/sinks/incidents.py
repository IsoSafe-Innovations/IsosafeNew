"""Incident sink abstraction."""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod

import numpy as np

from app.alerts.incidents import _save_snapshot, render_snapshot
from app.db.engine import get_engine
from app.db.tables import incidents
from app.metrics import ALERT_DISPATCH_LATENCY, INCIDENTS_FIRED
from app.redis_client import ALERT_CHANNEL, get_redis
from app.rules.engine import RuleFire

log = logging.getLogger(__name__)


class IncidentSink(ABC):
    @abstractmethod
    async def send_incident(
        self,
        camera_id: str,
        fire: RuleFire,
        image: np.ndarray,
        ts: float,
    ) -> int:
        pass


class LocalIncidentSink(IncidentSink):
    async def send_incident(
        self,
        camera_id: str,
        fire: RuleFire,
        image: np.ndarray,
        ts: float,
    ) -> int:
        snapshot_path = _save_snapshot(image, fire, camera_id, ts)
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                incidents.insert()
                .values(
                    camera_id=camera_id,
                    ts=dt.datetime.fromtimestamp(ts, tz=dt.UTC),
                    incident_type=fire.incident_type,
                    severity=fire.severity,
                    description=fire.description,
                    snapshot_path=snapshot_path,
                    status="open",
                )
                .returning(incidents.c.id)
            )
            incident_id = result.scalar_one()

        INCIDENTS_FIRED.labels(incident_type=fire.incident_type, severity=fire.severity).inc()
        payload = {
            "type": "incident",
            "id": incident_id,
            "camera_id": camera_id,
            "incident_type": fire.incident_type,
            "severity": fire.severity,
            "description": fire.description,
            "snapshot_url": f"/media/{snapshot_path}" if snapshot_path else None,
            "ts": dt.datetime.fromtimestamp(ts, tz=dt.UTC).isoformat(),
        }
        await get_redis().publish(ALERT_CHANNEL, json.dumps(payload))
        ALERT_DISPATCH_LATENCY.observe(time.time() - ts)
        log.info("incident %s: %s", fire.incident_type, fire.description, extra={"camera_id": camera_id})
        return incident_id


class CloudIncidentSink(IncidentSink):
    async def send_incident(
        self,
        camera_id: str,
        fire: RuleFire,
        image: np.ndarray,
        ts: float,
    ) -> int:
        """Agent-owned UUID -> queue -> POST incident -> PUT JPEG to presigned URL.

        No local DB or media write: the snapshot goes straight to S3 and the
        cloud owns the row (PRD v2 Phase 1a DD-05, DEMO-FR-03). Queueing decouples
        incident creation from a cloud outage; the outbox retries with backoff.
        """
        from app.agent.client import get_agent_client

        incident_uuid = str(uuid.uuid4())
        jpeg = render_snapshot(image, fire)
        payload = {
            "uuid": incident_uuid,
            "camera_id": camera_id,
            "rule_id": fire.rule_id,
            "type": fire.incident_type,
            "severity": fire.severity,
            "ts": ts,
            "details": {"description": fire.description},
            "has_snapshot": jpeg is not None,
        }

        # Hand off to the bounded outbox. Delivery is retried with backoff and
        # replays are idempotent because the UUID is agent-owned (DEMO-FR-21).
        client = get_agent_client()
        client.queue_incident(payload, jpeg)

        INCIDENTS_FIRED.labels(incident_type=fire.incident_type, severity=fire.severity).inc()
        ALERT_DISPATCH_LATENCY.observe(time.time() - ts)
        return 0
