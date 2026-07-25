"""Per-camera processing state: tracker, rule engine, zone tagging, OCR cadence,
heatmap grid, and live count publishing."""
import base64
import json
import logging
import time

import cv2
import numpy as np

from app.alerts.incidents import create_incident
from app.config import get_settings
from app.inference.ocr import DEDUP_SECONDS, read_plate
from app.inference.tracker import CentroidTracker
from app.inference.worker import VEHICLE_TYPES
from app.inference.writer import DetectionWriter
from app.metrics import FRAMES_PROCESSED
from app.redis_client import (
    COUNTS_KEY,
    FRAME_CHANNEL,
    HEATMAP_KEY_PREFIX,
    get_redis,
)
from app.rules.engine import CameraRuleEngine
from app.rules.zones import zones_containing

log = logging.getLogger(__name__)

HEATMAP_GRID = 32


class CameraProcessor:
    def __init__(self, camera_id: str, zones: list[dict], rules: list[dict],
                 writer: DetectionWriter, source_type: str = "rtsp"):
        self.camera_id = camera_id
        self.source_type = source_type
        self.zones = zones
        self.tracker = CentroidTracker()
        self.engine = CameraRuleEngine(camera_id, zones, rules)
        self.writer = writer
        self._processed_frames = 0
        self._last_counts_flush = 0.0
        self._last_frame_publish = 0.0

    def update_config(self, zones: list[dict], rules: list[dict]) -> None:
        self.zones = zones
        self.engine.update_config(zones, rules)

    def _publish_interval(self) -> float:
        fps = get_settings().dashboard_max_fps
        return 1.0 / min(max(fps, 2.0), 30.0)

    def _should_publish_frame(self) -> bool:
        now = time.time()
        if now - self._last_frame_publish < self._publish_interval():
            return False
        self._last_frame_publish = now
        return True

    async def process(self, image: np.ndarray, detections: list[dict], ts: float) -> None:
        """Handle one frame's detection results end-to-end."""
        settings = get_settings()
        self._processed_frames += 1
        FRAMES_PROCESSED.labels(camera_id=self.camera_id).inc()

        tracks = self.tracker.update(detections, now=ts)

        # Zone tagging + detection rows
        for det, track in zip(detections, tracks):
            zone_ids = zones_containing(track.centroid, self.zones)
            plate_text = None
            plate_conf = None
            if (
                track.object_type in VEHICLE_TYPES
                and self._processed_frames % settings.ocr_every_n_frames == 0
            ):
                result = await read_plate(image, track.bbox, settings.plate_confidence)
                if result:
                    text, conf = result
                    # per-track dedup within 60s
                    if not (track.last_plate == text and ts - track.last_plate_ts < DEDUP_SECONDS):
                        plate_text, plate_conf = text, conf
                        track.last_plate = text
                        track.last_plate_ts = ts
            await self.writer.add(
                self.camera_id, ts, track.object_type, det["confidence"],
                track.track_id, track.bbox, zone_ids, plate_text, plate_conf,
            )

        # Rules
        fires = self.engine.evaluate(tracks, now=ts)
        for fire in fires:
            try:
                await create_incident(self.camera_id, fire, image, ts)
            except Exception:
                log.exception("incident creation failed", extra={"camera_id": self.camera_id})

        # Heatmap grid increments (person tracks only)
        await self._update_heatmap(tracks)

        # Live counts + frame publish
        await self._publish(image, tracks, ts)

    async def publish_preview(self, image: np.ndarray, ts: float) -> None:
        """Unannotated frame while inference runs; throttled with annotated publishes."""
        if not self._should_publish_frame():
            return
        await self._send_frame(image, tracks=None, ts=ts)

    async def _send_frame(self, image: np.ndarray, tracks, ts: float) -> None:
        settings = get_settings()
        in_frame: dict[str, int] = {}
        if tracks:
            for track in tracks:
                in_frame[track.object_type] = in_frame.get(track.object_type, 0) + 1
            out = self._annotate(image, tracks)
        else:
            out = image
        h, w = out.shape[:2]
        if max(h, w) > 960:
            scale = 960 / max(h, w)
            out = cv2.resize(out, (int(w * scale), int(h * scale)))
        ok, buf = cv2.imencode(
            ".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, settings.frame_jpeg_quality]
        )
        if not ok:
            return
        message = {
            "type": "frame",
            "camera_id": self.camera_id,
            "image": base64.b64encode(buf.tobytes()).decode(),
            "counts": dict(self.tracker.session_counts),
            "in_frame": in_frame,
            "ts": ts,
        }
        await get_redis().publish(FRAME_CHANNEL, json.dumps(message))

    async def _update_heatmap(self, tracks) -> None:
        r = get_redis()
        key = HEATMAP_KEY_PREFIX + self.camera_id
        pipe = r.pipeline(transaction=False)
        touched = False
        for track in tracks:
            if track.object_type != "person":
                continue
            gx = min(HEATMAP_GRID - 1, max(0, int(track.centroid[0] * HEATMAP_GRID)))
            gy = min(HEATMAP_GRID - 1, max(0, int(track.centroid[1] * HEATMAP_GRID)))
            pipe.hincrby(key, f"{gx}:{gy}", 1)
            touched = True
        if touched:
            pipe.expire(key, 7200)
            await pipe.execute()

    async def _publish(self, image: np.ndarray, tracks, ts: float) -> None:
        settings = get_settings()
        in_frame: dict[str, int] = {}
        for track in tracks:
            in_frame[track.object_type] = in_frame.get(track.object_type, 0) + 1

        counts = {
            "in_frame": in_frame,
            "session": dict(self.tracker.session_counts),
            "ts": ts,
        }
        r = get_redis()
        now = time.time()
        if now - self._last_counts_flush >= 1.0:
            self._last_counts_flush = now
            await r.hset(COUNTS_KEY, self.camera_id, json.dumps(counts))

        # Live counts + annotated frame (RTSP/live sources only; file uses preview path)
        if self.source_type == "file":
            return
        if not self._should_publish_frame():
            return
        await self._send_frame(image, tracks, ts)

    def _annotate(self, image: np.ndarray, tracks) -> np.ndarray:
        out = image.copy()
        h, w = out.shape[:2]
        # keep publish size bounded
        if max(h, w) > 960:
            scale = 960 / max(h, w)
            out = cv2.resize(out, (int(w * scale), int(h * scale)))
            h, w = out.shape[:2]
        for track in tracks:
            b = track.bbox
            color = (80, 200, 120) if track.object_type == "person" else (255, 180, 60)
            pt1 = (int(b[0] * w), int(b[1] * h))
            pt2 = (int(b[2] * w), int(b[3] * h))
            cv2.rectangle(out, pt1, pt2, color, 2)
            label = f"{track.object_type} #{track.track_id}"
            if track.last_plate:
                label += f" [{track.last_plate}]"
            cv2.putText(out, label, (pt1[0], max(14, pt1[1] - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        return out
