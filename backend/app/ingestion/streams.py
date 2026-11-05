"""Camera stream readers.

Each camera runs as an asyncio task that continuously reads frames and enqueues
every Nth frame into a bounded queue (maxsize 2). When full, the oldest frame is
dropped: detection must always run on fresh frames, never a stale backlog.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field

import cv2
import httpx
import numpy as np

from app.config import get_settings
from app.ingestion.health import CameraHealth
from app.ingestion.youtube import resolve_live
from app.metrics import FRAMES_DROPPED, QUEUE_DEPTH

log = logging.getLogger(__name__)

RECONNECT_BACKOFF = [1, 2, 4, 8, 16, 30]  # seconds, capped at 30


@dataclass
class Frame:
    camera_id: str
    image: np.ndarray
    ts: float
    seq: int


@dataclass
class CameraStream:
    """One per camera. Owns the read loop and the bounded frame queue."""

    camera_id: str
    source: str
    source_type: str  # rtsp | snapshot_url | file
    refresh_secs: float = 2.0
    loop_file: bool = True
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=2))
    health: CameraHealth | None = None

    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _seq: int = 0

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _enqueue(self, image: np.ndarray) -> None:
        """Drop-oldest enqueue. Never blocks the read loop."""
        frame = Frame(self.camera_id, image, time.time(), self._seq)
        self._seq += 1
        while True:
            try:
                self.queue.put_nowait(frame)
                break
            except asyncio.QueueFull:
                try:
                    self.queue.get_nowait()
                    FRAMES_DROPPED.labels(camera_id=self.camera_id).inc()
                    if self.health:
                        self.health.frames_dropped += 1
                except asyncio.QueueEmpty:
                    pass
        QUEUE_DEPTH.labels(camera_id=self.camera_id).set(self.queue.qsize())

    async def run(self) -> None:
        """Top-level loop with reconnect backoff. Never raises."""
        backoff_idx = 0
        while not self._stop.is_set():
            try:
                if self.source_type == "rtsp":
                    ok = await self._run_capture(self.source, realtime=True)
                elif self.source_type == "youtube":
                    # Resolve anew after disconnects: YouTube media URLs expire.
                    source = await asyncio.to_thread(resolve_live, self.source)
                    ok = await self._run_capture(source, realtime=True)
                elif self.source_type == "file":
                    ok = await self._run_capture(self.source, realtime=False)
                    if ok and not self.loop_file:
                        return  # single-pass upload processing
                elif self.source_type == "snapshot_url":
                    ok = await self._run_snapshot()
                else:
                    log.error("unknown source type", extra={"camera_id": self.camera_id})
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("stream loop error", extra={"camera_id": self.camera_id})
                if self.health and self.source_type == "youtube":
                    self.health.error = "YouTube analysis connection failed; retrying automatically"
                ok = False

            if self._stop.is_set():
                return
            delay = RECONNECT_BACKOFF[min(backoff_idx, len(RECONNECT_BACKOFF) - 1)]
            backoff_idx = 0 if ok else backoff_idx + 1
            if self.health:
                await self.health.record_reconnect()
            log.warning(
                "stream ended, reconnecting in %ss", delay, extra={"camera_id": self.camera_id}
            )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def _run_capture(self, source: str, realtime: bool) -> bool:
        """RTSP or file playback via OpenCV. Returns True if it read frames successfully."""
        settings = get_settings()
        every_n = max(1, settings.process_every_n_frames)
        loop = asyncio.get_running_loop()

        cap = await loop.run_in_executor(None, self._open_capture, source)
        if cap is None or not cap.isOpened():
            return False

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if not (1.0 <= fps <= 120.0):
            fps = 25.0
        frame_interval = 1.0 / fps
        read_any = False
        frame_no = 0
        try:
            while not self._stop.is_set():
                t0 = time.monotonic()
                ret, image = await loop.run_in_executor(None, cap.read)
                if not ret or image is None:
                    if self.source_type == "file" and read_any:
                        if self.loop_file and not self._stop.is_set():
                            # Re-open for a reliable loop (seek-to-zero is flaky on some MP4s).
                            await loop.run_in_executor(None, cap.release)
                            cap = await loop.run_in_executor(None, self._open_capture, source)
                            if cap is None or not cap.isOpened():
                                return True
                            frame_no = 0
                            continue
                        return True
                    return read_any
                read_any = True
                frame_no += 1
                if frame_no % every_n == 0:
                    self._enqueue(image)
                    if self.health:
                        await self.health.record_frame()
                if self.source_type == "youtube":
                    # HLS arrives in segments and OpenCV can decode a whole
                    # segment in a burst. Pace at source FPS so tracking sees
                    # regular motion instead of jumping several seconds at once.
                    elapsed = time.monotonic() - t0
                    await asyncio.sleep(max(0.0, frame_interval - elapsed))
                elif realtime:
                    # RTSP delivers at source rate; yield so other tasks run.
                    await asyncio.sleep(0)
                elif self.source_type == "file":
                    # Demo/file sources: pace reads for smooth dashboard playback.
                    target_fps = settings.file_playback_fps or fps
                    target_fps = min(max(target_fps, 5.0), 30.0)
                    elapsed = time.monotonic() - t0
                    await asyncio.sleep(max(0.0, (1.0 / target_fps) - elapsed))
                else:
                    elapsed = time.monotonic() - t0
                    await asyncio.sleep(max(0.0, frame_interval - elapsed))
        finally:
            await loop.run_in_executor(None, cap.release)
        return True

    def _open_capture(self, source: str) -> cv2.VideoCapture | None:
        try:
            if self.source_type in {"rtsp", "youtube"}:
                cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000,
                ])
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # always read the freshest frame
            else:
                cap = cv2.VideoCapture(source)
            return cap
        except Exception:
            log.exception("failed to open capture", extra={"camera_id": self.camera_id})
            return None

    async def _run_snapshot(self) -> bool:
        """HTTP snapshot polling with prefetch: fetch the next image while the
        current one sits in the inference queue."""
        interval = max(0.2, float(self.refresh_secs))
        read_any = False
        async with httpx.AsyncClient(timeout=10.0) as client:
            pending: asyncio.Task | None = asyncio.create_task(self._fetch(client))
            while not self._stop.is_set():
                t0 = time.monotonic()
                image = await pending
                pending = asyncio.create_task(self._fetch(client))  # prefetch next
                if image is not None:
                    read_any = True
                    self._enqueue(image)
                    if self.health:
                        await self.health.record_frame()
                elif not read_any:
                    pending.cancel()
                    return False
                elapsed = time.monotonic() - t0
                await asyncio.sleep(max(0.0, interval - elapsed))
            pending.cancel()
        return read_any

    async def _fetch(self, client: httpx.AsyncClient) -> np.ndarray | None:
        try:
            resp = await client.get(self.source)
            resp.raise_for_status()
            arr = np.frombuffer(resp.content, dtype=np.uint8)
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception:
            log.warning("snapshot fetch failed", extra={"camera_id": self.camera_id})
            return None
