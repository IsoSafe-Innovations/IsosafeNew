"""Per-camera processing state: tracker, rule engine, zone tagging, OCR cadence,
heatmap grid, and live count publishing."""
import asyncio
import logging
import time
import uuid

import numpy as np

from app.config import get_settings
from app.inference.ocr import DEDUP_SECONDS, read_plate
from app.inference.advanced_tracker import make_tracker
from app.inference.options import resolve_options
from app.inference.plates import PlateConsensus
from app.inference.telemetry import AnalysisTelemetry
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
                 writer: DetectionWriter, source_type: str = "rtsp", analysis_config: dict | None = None):
        self.camera_id = camera_id
        self.source_type = source_type
        self.zones = zones
        self.analysis_options = resolve_options(analysis_config)
        self.tracker = make_tracker(self.analysis_options)
        self.engine = CameraRuleEngine(camera_id, zones, rules, self.analysis_options["confirmation_frames"])
        self.telemetry = AnalysisTelemetry(camera_id, self.analysis_options)
        self.writer = writer
        self._processed_frames = 0
        self._last_counts_flush = 0.0
        self._last_frame_publish = 0.0
        self._ocr_task: asyncio.Task | None = None
        self._ocr_track_id: int | None = None
        self._plate_results: dict[int, tuple[str, float, float]] = {}
        self._plate_consensus = {}
        self._ocr_capture_ts = None
        self._ocr_scheduled_at = None
        self.tracking_session = uuid.uuid4()

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
        # OCR can download models or take seconds on CPU. Keep one job in flight
        # per camera, without blocking detection, rules, or other cameras.
        if self._ocr_task is not None and self._ocr_task.done():
            try:
                result = self._ocr_task.result()
                if result:
                    text, confidence = result
                    consensus = self._plate_consensus.setdefault(self._ocr_track_id, PlateConsensus(get_settings().plate_consensus_reads))
                    agreed = consensus.add(text, confidence, self._ocr_capture_ts)
                    if agreed:
                        self._plate_results[self._ocr_track_id] = (*agreed, ts)
                    self.telemetry.ocr_state = "confirmed" if agreed else "waiting_for_consensus"
                else:
                    self.telemetry.ocr_state = "insufficient_detail"
            except Exception:
                self.telemetry.ocr_state = "error"
                log.exception("background plate reading failed", extra={"camera_id": self.camera_id})
            self._ocr_task = None
        self._plate_consensus = {tid: c for tid,c in self._plate_consensus.items() if tid in self.tracker.tracks}
        self._plate_results = {
            tid: result for tid, result in self._plate_results.items()
            if ts - result[2] < DEDUP_SECONDS and tid in self.tracker.tracks
        }

        # Zone tagging + detection rows
        for det, track in zip(detections, tracks):
            if track is None:
                continue
            zone_ids = zones_containing(track.centroid, self.zones)
            plate_text = None
            plate_conf = None
            pending = self._plate_results.pop(track.track_id, None)
            if pending:
                text, conf, _ = pending
                if not (track.last_plate == text and ts - track.last_plate_ts < DEDUP_SECONDS):
                    plate_text, plate_conf = text, conf
                    track.last_plate, track.last_plate_ts = text, ts
            if (
                track.object_type in VEHICLE_TYPES
                and self._processed_frames % settings.ocr_every_n_frames == 0
                and self._ocr_task is None
                and self.analysis_options["plate_reading"]
            ):
                self._ocr_track_id = track.track_id
                self._ocr_capture_ts = ts
                self._ocr_scheduled_at = time.monotonic()
                self.telemetry.ocr_state = "busy"
                self._ocr_task = asyncio.create_task(
                    read_plate(image, list(track.bbox), settings.plate_confidence)
                )
            await self.writer.add(
                self.camera_id, ts, track.object_type, det["confidence"],
                track.track_id, track.bbox, zone_ids, plate_text, plate_conf,
            )

        # Rules
        tracks = [t for t in tracks if t is not None and t.hits >= self.analysis_options["confirmation_frames"]]
        fires = self.engine.evaluate(tracks, now=ts)
        for event in self.engine.crossing_events:
            event["session_id"] = self.tracking_session
            await self.writer.add_crossing(self.camera_id, event)
        self.engine.crossing_events.clear()
        self.telemetry.crossings = self.engine.crossing_counts
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
            "crossings": dict(self.engine.crossing_counts),
            "counting_mode": "line_crossings" if any(r.get("type") == "line_crossing" for r in self.engine.rules) else "confirmed_tracks",
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
