"""Incident creation: DB row + annotated snapshot + Redis publish."""
import datetime as dt
import json
import logging
import os
import time

import cv2
import numpy as np
import sqlalchemy as sa

from app.config import get_settings
from app.db.engine import get_engine
from app.db.tables import incidents
from app.inference.tracker import Track
from app.metrics import ALERT_DISPATCH_LATENCY, INCIDENTS_FIRED
from app.redis_client import ALERT_CHANNEL, get_redis
from app.rules.engine import RuleFire

log = logging.getLogger(__name__)

SEVERITY_COLORS = {"info": (255, 160, 40), "warning": (0, 180, 255), "critical": (0, 0, 255)}

_snapshots_paused = False


def set_snapshots_paused(paused: bool) -> None:
    """Disk-space guard hook: pause snapshot writes when the disk is nearly full."""
    global _snapshots_paused
    _snapshots_paused = paused


def _save_snapshot(image: np.ndarray, fire: RuleFire, camera_id: str, ts: float) -> str | None:
    if _snapshots_paused:
        return None
    settings = get_settings()
    day = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")
    directory = os.path.join(settings.media_root, "snapshots", day)
    os.makedirs(directory, exist_ok=True)
    filename = f"{camera_id}_{int(ts * 1000)}_{fire.incident_type}.jpg"
    path = os.path.join(directory, filename)

    annotated = image.copy()
    if fire.track is not None:
        h, w = annotated.shape[:2]
        b = fire.track.bbox
        color = SEVERITY_COLORS.get(fire.severity, (0, 0, 255))
        pt1 = (int(b[0] * w), int(b[1] * h))
        pt2 = (int(b[2] * w), int(b[3] * h))
        cv2.rectangle(annotated, pt1, pt2, color, 3)
        cv2.putText(annotated, fire.incident_type, (pt1[0], max(20, pt1[1] - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    ok = cv2.imwrite(path, annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        log.error("snapshot write failed: %s", path)
        return None
    return os.path.relpath(path, settings.media_root)


async def create_incident(camera_id: str, fire: RuleFire, image: np.ndarray, ts: float) -> int:
    """Write incident row, save annotated snapshot, publish to Redis. Returns incident id."""
    snapshot_path = _save_snapshot(image, fire, camera_id, ts)
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.insert(incidents)
            .values(
                camera_id=camera_id,
                ts=dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc),
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
        "ts": dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).isoformat(),
    }
    await get_redis().publish(ALERT_CHANNEL, json.dumps(payload))
    ALERT_DISPATCH_LATENCY.observe(time.time() - ts)
    log.info("incident %s: %s", fire.incident_type, fire.description,
             extra={"camera_id": camera_id})
    return incident_id
