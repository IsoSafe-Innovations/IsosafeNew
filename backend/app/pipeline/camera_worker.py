"""Per-camera processing state: tracker, rule engine, zone tagging, OCR cadence,
heatmap grid, and live count publishing."""
import logging
import time

import numpy as np

from app.config import get_settings
from app.inference.ocr import DEDUP_SECONDS, read_plate
from app.inference.tracker import CentroidTracker
from app.inference.worker import VEHICLE_TYPES
from app.inference.writer import DetectionWriter
from app.metrics import FRAMES_PROCESSED
from app.rules.engine import CameraRuleEngine
from app.rules.zones import zones_containing
from app.sinks.factory import get_frame_sink, get_incident_sink

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
        settings = get_settings()
        # Cloud demo caps the live uplink at AGENT_LIVE_FPS (default 2).
        fps = settings.agent_live_fps if settings.agent_mode else settings.dashboard_max_fps
        return 1.0 / min(max(fps, 1.0), 30.0)

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
                sink = get_incident_sink()
                await sink.send_incident(self.camera_id, fire, image, ts)
            except Exception:
                log.exception("incident creation failed", extra={"camera_id": self.camera_id})

        # Heatmap grid increments (person tracks only)
        await self._update_heatmap(tracks)

        # Live counts + frame publish
        await self._publish(image, tracks, ts)

    async def _send_frame(self, image: np.ndarray, tracks, ts: float) -> None:
        in_frame: dict[str, int] = {}
        if tracks:
            for track in tracks:
                in_frame[track.object_type] = in_frame.get(track.object_type, 0) + 1
        sink = get_frame_sink()
        await sink.publish_frame(
            self.camera_id,
            image,
            tracks,
            ts,
            counts=dict(self.tracker.session_counts),
            in_frame=in_frame,
        )

    async def _update_heatmap(self, tracks) -> None:
        sink = get_frame_sink()
        await sink.update_heatmap(self.camera_id, tracks)

    async def _publish(self, image: np.ndarray, tracks, ts: float) -> None:
        in_frame: dict[str, int] = {}
        for track in tracks:
            in_frame[track.object_type] = in_frame.get(track.object_type, 0) + 1

        counts = {
            "in_frame": in_frame,
            "session": dict(self.tracker.session_counts),
            "ts": ts,
        }
        now = time.time()
        if now - self._last_counts_flush >= 1.0:
            self._last_counts_flush = now
            sink = get_frame_sink()
            await sink.update_counts(self.camera_id, counts)

        # Annotated live frame (all source types, including looping file demos),
        # throttled to the dashboard/agent live FPS cap.
        if not self._should_publish_frame():
            return
        await self._send_frame(image, tracks, ts)
