"""Frame sink abstraction."""
from __future__ import annotations

import base64
import json
import logging
from abc import ABC, abstractmethod

import cv2
import numpy as np

from app.agent.client import get_agent_client
from app.config import get_settings
from app.redis_client import COUNTS_KEY, FRAME_CHANNEL, HEATMAP_KEY_PREFIX, get_redis

log = logging.getLogger(__name__)

HEATMAP_GRID = 32


class FrameSink(ABC):
    @abstractmethod
    async def publish_frame(
        self,
        camera_id: str,
        image: np.ndarray,
        tracks: list | None,
        ts: float,
        counts: dict | None = None,
        in_frame: dict | None = None,
    ) -> None:
        pass

    @abstractmethod
    async def update_counts(self, camera_id: str, counts: dict) -> None:
        pass

    @abstractmethod
    async def update_heatmap(self, camera_id: str, tracks: list) -> None:
        pass


def _annotate(image: np.ndarray, tracks) -> np.ndarray:
    out = image.copy()
    h, w = out.shape[:2]
    for t in tracks:
        b = t.bbox
        color = (80, 200, 120) if getattr(t, "object_type", None) == "person" else (255, 180, 60)
        pt1 = (int(b[0] * w), int(b[1] * h))
        pt2 = (int(b[2] * w), int(b[3] * h))
        cv2.rectangle(out, pt1, pt2, color, 2)
        label = f"{getattr(t, 'object_type', 'obj')} #{getattr(t, 'track_id', '?')}"
        plate = getattr(t, "last_plate", None)
        if plate:
            label += f" [{plate}]"
        cv2.putText(
            out, label, (pt1[0], max(14, pt1[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1
        )
    return out


def _render_frame(image: np.ndarray, tracks: list | None) -> bytes | None:
    """Annotate (when tracks present), bound to 960px, and JPEG-encode."""
    out = _annotate(image, tracks) if tracks else image
    h, w = out.shape[:2]
    if max(h, w) > 960:
        scale = 960 / max(h, w)
        out = cv2.resize(out, (int(w * scale), int(h * scale)))
    ok, buf = cv2.imencode(
        ".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, get_settings().frame_jpeg_quality]
    )
    return buf.tobytes() if ok else None


def _frame_message(
    camera_id: str,
    jpeg: bytes,
    counts: dict | None,
    in_frame: dict | None,
    ts: float,
) -> dict:
    """The on-the-wire frame payload shared by the local and cloud paths."""
    return {
        "type": "frame",
        "camera_id": camera_id,
        "image": base64.b64encode(jpeg).decode(),
        "counts": counts or {},
        "in_frame": in_frame or {},
        "ts": ts,
    }


class LocalRedisFrameSink(FrameSink):
    async def publish_frame(
        self,
        camera_id: str,
        image: np.ndarray,
        tracks: list | None,
        ts: float,
        counts: dict | None = None,
        in_frame: dict | None = None,
    ) -> None:
        jpeg = _render_frame(image, tracks)
        if jpeg is None:
            return
        message = _frame_message(camera_id, jpeg, counts, in_frame, ts)
        await get_redis().publish(FRAME_CHANNEL, json.dumps(message))

    async def update_counts(self, camera_id: str, counts: dict) -> None:
        await get_redis().hset(COUNTS_KEY, camera_id, json.dumps(counts))

    async def update_heatmap(self, camera_id: str, tracks: list) -> None:
        r = get_redis()
        key = HEATMAP_KEY_PREFIX + camera_id
        pipe = r.pipeline(transaction=False)
        touched = False
        for track in tracks:
            if getattr(track, "object_type", None) != "person":
                continue
            gx = min(HEATMAP_GRID - 1, max(0, int(track.centroid[0] * HEATMAP_GRID)))
            gy = min(HEATMAP_GRID - 1, max(0, int(track.centroid[1] * HEATMAP_GRID)))
            pipe.hincrby(key, f"{gx}:{gy}", 1)
            touched = True
        if touched:
            pipe.expire(key, 86400)
            await pipe.execute()


class CloudFrameSink(FrameSink):
    """Sends the same frame payload over the agent live-stream socket.

    The cloud republishes it verbatim on FRAME_CHANNEL, so the dashboard sees an
    identical message whether the pipeline runs locally or on a site agent.
    """

    async def publish_frame(
        self,
        camera_id: str,
        image: np.ndarray,
        tracks: list | None,
        ts: float,
        counts: dict | None = None,
        in_frame: dict | None = None,
    ) -> None:
        jpeg = _render_frame(image, tracks)
        if jpeg is None:
            return
        message = _frame_message(camera_id, jpeg, counts, in_frame, ts)
        await get_agent_client().send_frame(message)

    async def update_counts(self, camera_id: str, counts: dict) -> None:
        # Counts are embedded in each frame message on the cloud path.
        pass

    async def update_heatmap(self, camera_id: str, tracks: list) -> None:
        pass
