"""Annotated snapshot rendering shared by the local and cloud incident sinks."""
import datetime as dt
import logging
import os

import cv2
import numpy as np

from app.config import get_settings
from app.rules.engine import RuleFire

log = logging.getLogger(__name__)

SEVERITY_COLORS = {"info": (255, 160, 40), "warning": (0, 180, 255), "critical": (0, 0, 255)}

_snapshots_paused = False


def set_snapshots_paused(paused: bool) -> None:
    """Disk-space guard hook: pause snapshot writes when the disk is nearly full."""
    global _snapshots_paused
    _snapshots_paused = paused


def render_snapshot(image: np.ndarray, fire: RuleFire) -> bytes | None:
    """Annotate the triggering frame and return JPEG bytes, or None on failure.

    Agent mode uploads these bytes straight to S3; local mode writes them to disk.
    """
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
    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return None
    return buf.tobytes()


def _save_snapshot(image: np.ndarray, fire: RuleFire, camera_id: str, ts: float) -> str | None:
    if _snapshots_paused:
        return None
    settings = get_settings()
    day = dt.datetime.fromtimestamp(ts, tz=dt.UTC).strftime("%Y-%m-%d")
    directory = os.path.join(settings.media_root, "snapshots", day)
    os.makedirs(directory, exist_ok=True)
    filename = f"{camera_id}_{int(ts * 1000)}_{fire.incident_type}.jpg"
    path = os.path.join(directory, filename)

    data = render_snapshot(image, fire)
    if data is None:
        log.error("snapshot encode failed: %s", path)
        return None
    try:
        with open(path, "wb") as fh:
            fh.write(data)
    except OSError:
        log.exception("snapshot write failed: %s", path)
        return None
    return os.path.relpath(path, settings.media_root)
