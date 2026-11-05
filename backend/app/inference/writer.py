"""Batched detection writer: asyncpg executemany, flushed every 2s or 200 rows.

Never inserts row-by-row inside the frame loop.
"""
import asyncio
import datetime as dt
import logging
import uuid

from app.config import get_settings
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

CROSSING_SQL = """
INSERT INTO crossing_events (camera_id, session_id, rule_id, track_id, direction, count_as, object_type, ts)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT DO NOTHING
"""


class DetectionWriter:
    def __init__(self) -> None:
        self._buffer: list[tuple] = []
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self._crossings: list[tuple] = []
        self.session_id = uuid.uuid4()

    async def add_crossing(self, camera_id, event):
        async with self._lock:
            self._crossings.append((camera_id, event.get("session_id", self.session_id), event["rule_id"], event["track_id"],
                event["direction"], event["count_as"], event["object_type"],
                dt.datetime.fromtimestamp(event["ts"], tz=dt.UTC)))
            flush = len(self._crossings) >= FLUSH_ROWS
        if flush:
            await self._flush()

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
            dt.datetime.fromtimestamp(ts, tz=dt.UTC),
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
            except TimeoutError:
                pass
            await self._flush()

    async def _flush(self) -> None:
        settings = get_settings()
        if settings.agent_mode:
            # In agent mode, detections are handled by agent; don't write to local DB
            async with self._lock:
                self._buffer = []
                self._crossings = []
            return
        async with self._lock:
            if not self._buffer and not self._crossings:
                return
            rows, self._buffer = self._buffer, []
            crossings, self._crossings = self._crossings, []
        try:
            pool = await get_asyncpg_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    if rows:
                        await conn.executemany(INSERT_SQL, rows)
                    if crossings:
                        await conn.executemany(CROSSING_SQL, crossings)
            DETECTIONS_WRITTEN.inc(len(rows))
        except Exception:
            log.exception("detection flush failed, re-buffering %d rows", len(rows))
            async with self._lock:
                # keep at most one extra batch to avoid unbounded growth on outage
                self._buffer = (rows + self._buffer)[: FLUSH_ROWS * 2]
                pending = crossings + self._crossings
                if len(pending)>FLUSH_ROWS*2:
                    log.critical("crossing persistence buffer full; %d events could not be retained",len(pending)-FLUSH_ROWS*2)
                self._crossings = pending[: FLUSH_ROWS*2]
