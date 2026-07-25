"""Batched detection writer: asyncpg executemany, flushed every 2s or 200 rows.

Never inserts row-by-row inside the frame loop.
"""
import asyncio
import datetime as dt
import logging

from app.db.engine import get_asyncpg_pool
from app.metrics import DETECTIONS_WRITTEN

log = logging.getLogger(__name__)

FLUSH_INTERVAL = 2.0
FLUSH_ROWS = 200

INSERT_SQL = """
INSERT INTO detections
  (camera_id, ts, object_type, confidence, track_id, bbox, zone_ids, plate_text, plate_confidence)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
"""


class DetectionWriter:
    def __init__(self) -> None:
        self._buffer: list[tuple] = []
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped.clear()
        self._task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        self._stopped.set()
        if self._task:
            await self._task
        await self._flush()

    async def add(
        self,
        camera_id: str,
        ts: float,
        object_type: str,
        confidence: float,
        track_id: int | None,
        bbox: list[float],
        zone_ids: list[str],
        plate_text: str | None = None,
        plate_confidence: float | None = None,
    ) -> None:
        row = (
            camera_id,
            dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc),
            object_type,
            confidence,
            track_id,
            bbox,
            zone_ids or None,
            plate_text,
            plate_confidence,
        )
        flush_now = False
        async with self._lock:
            self._buffer.append(row)
            flush_now = len(self._buffer) >= FLUSH_ROWS
        if flush_now:
            await self._flush()

    async def _flush_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=FLUSH_INTERVAL)
            except asyncio.TimeoutError:
                pass
            await self._flush()

    async def _flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            rows, self._buffer = self._buffer, []
        try:
            pool = await get_asyncpg_pool()
            async with pool.acquire() as conn:
                await conn.executemany(INSERT_SQL, rows)
            DETECTIONS_WRITTEN.inc(len(rows))
        except Exception:
            log.exception("detection flush failed, re-buffering %d rows", len(rows))
            async with self._lock:
                # keep at most one extra batch to avoid unbounded growth on outage
                self._buffer = (rows + self._buffer)[: FLUSH_ROWS * 2]
