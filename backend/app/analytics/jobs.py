"""Analytics aggregation.

- Every 5 minutes: upsert analytics_hourly for the current bucket from raw detections.
- Hourly: snapshot per-camera heatmap grids from Redis to disk.
- Nightly: daily rollups, snapshot pruning, stuck upload-job cleanup.
"""
import asyncio
import datetime as dt
import json
import logging
import os
import time

import sqlalchemy as sa

from app.config import get_settings
from app.db.engine import get_engine
from app.redis_client import HEATMAP_KEY_PREFIX, get_redis

log = logging.getLogger(__name__)

AGGREGATION_INTERVAL = 300  # 5 minutes
HEATMAP_GRID = 32

HOURLY_UPSERT = sa.text("""
INSERT INTO analytics_hourly
  (camera_id, bucket, footfall, vehicles, avg_queue, max_queue, avg_occupancy, incident_count)
SELECT
  d.camera_id,
  date_trunc('hour', d.ts) AS bucket,
  COUNT(DISTINCT d.track_id) FILTER (WHERE d.object_type = 'person') AS footfall,
  COALESCE(veh.vehicles, '{}'::jsonb) AS vehicles,
  COALESCE(q.avg_queue, 0),
  COALESCE(q.max_queue, 0),
  COALESCE(o.avg_occupancy, 0),
  COALESCE(i.incident_count, 0)
FROM detections d
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(v.object_type, v.cnt) AS vehicles FROM (
        SELECT d2.object_type, COUNT(DISTINCT d2.track_id) AS cnt
        FROM detections d2
        WHERE d2.camera_id = d.camera_id
          AND date_trunc('hour', d2.ts) = date_trunc('hour', d.ts)
          AND d2.object_type IN ('car','motorcycle','bus','truck')
        GROUP BY d2.object_type
     ) v
) veh ON true
LEFT JOIN LATERAL (
    SELECT AVG(c)::real AS avg_queue, MAX(c)::int AS max_queue FROM (
      SELECT COUNT(*) AS c FROM detections dq
      WHERE dq.camera_id = d.camera_id
        AND date_trunc('hour', dq.ts) = date_trunc('hour', d.ts)
        AND dq.object_type = 'person' AND dq.zone_ids IS NOT NULL
      GROUP BY date_trunc('second', dq.ts)
    ) s
) q ON true
LEFT JOIN LATERAL (
    SELECT AVG(c)::real AS avg_occupancy FROM (
      SELECT COUNT(DISTINCT do2.track_id) AS c FROM detections do2
      WHERE do2.camera_id = d.camera_id
        AND date_trunc('hour', do2.ts) = date_trunc('hour', d.ts)
        AND do2.object_type = 'person'
      GROUP BY date_trunc('minute', do2.ts)
    ) s
) o ON true
LEFT JOIN LATERAL (
    SELECT COUNT(*)::int AS incident_count FROM incidents ic
    WHERE ic.camera_id = d.camera_id
      AND date_trunc('hour', ic.ts) = date_trunc('hour', d.ts)
) i ON true
WHERE d.ts >= :bucket_start AND d.ts < :bucket_end
GROUP BY d.camera_id, date_trunc('hour', d.ts), q.avg_queue, q.max_queue,
         o.avg_occupancy, i.incident_count
ON CONFLICT (camera_id, bucket) DO UPDATE SET
  footfall = EXCLUDED.footfall,
  vehicles = EXCLUDED.vehicles,
  avg_queue = EXCLUDED.avg_queue,
  max_queue = EXCLUDED.max_queue,
  avg_occupancy = EXCLUDED.avg_occupancy,
  incident_count = EXCLUDED.incident_count
""")

DAILY_ROLLUP = sa.text("""
INSERT INTO analytics_daily
  (camera_id, day, footfall, vehicles, avg_queue, max_queue, avg_occupancy,
   incident_count, peak_hour)
SELECT
  camera_id,
  (bucket AT TIME ZONE 'UTC')::date AS day,
  SUM(footfall),
  COALESCE((
    SELECT jsonb_object_agg(k, total) FROM (
      SELECT key AS k, SUM(value::int) AS total
      FROM analytics_hourly ah2, jsonb_each_text(ah2.vehicles)
      WHERE ah2.camera_id = ah.camera_id
        AND (ah2.bucket AT TIME ZONE 'UTC')::date = (ah.bucket AT TIME ZONE 'UTC')::date
      GROUP BY key
    ) t), '{}'::jsonb),
  AVG(avg_queue)::real,
  MAX(max_queue),
  AVG(avg_occupancy)::real,
  SUM(incident_count),
  (ARRAY_AGG(EXTRACT(hour FROM bucket)::int ORDER BY footfall DESC))[1]
FROM analytics_hourly ah
WHERE (bucket AT TIME ZONE 'UTC')::date = :day
GROUP BY camera_id, (bucket AT TIME ZONE 'UTC')::date
ON CONFLICT (camera_id, day) DO UPDATE SET
  footfall = EXCLUDED.footfall,
  vehicles = EXCLUDED.vehicles,
  avg_queue = EXCLUDED.avg_queue,
  max_queue = EXCLUDED.max_queue,
  avg_occupancy = EXCLUDED.avg_occupancy,
  incident_count = EXCLUDED.incident_count,
  peak_hour = EXCLUDED.peak_hour
""")


async def aggregate_current_hour() -> None:
    now = dt.datetime.now(dt.UTC)
    bucket_start = now.replace(minute=0, second=0, microsecond=0)
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            HOURLY_UPSERT,
            {"bucket_start": bucket_start, "bucket_end": bucket_start + dt.timedelta(hours=1)},
        )


async def snapshot_heatmaps() -> None:
    """Persist Redis heatmap grids to local object storage, then reset them."""
    settings = get_settings()
    r = get_redis()
    directory = os.path.join(settings.media_root, "heatmaps")
    os.makedirs(directory, exist_ok=True)
    hour_tag = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H")
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor, match=HEATMAP_KEY_PREFIX + "*", count=100)
        for key in keys:
            camera_id = key.removeprefix(HEATMAP_KEY_PREFIX)
            raw = await r.hgetall(key)
            grid = [[0] * HEATMAP_GRID for _ in range(HEATMAP_GRID)]
            for cell, count in raw.items():
                gx, gy = map(int, cell.split(":"))
                grid[gy][gx] = int(count)
            path = os.path.join(directory, f"{camera_id}_{hour_tag}.json")
            with open(path, "w") as f:
                json.dump({"camera_id": camera_id, "hour": hour_tag, "grid": grid}, f)
            # keep a rolling "latest" copy for the dashboard overlay
            with open(os.path.join(directory, f"{camera_id}_latest.json"), "w") as f:
                json.dump({"camera_id": camera_id, "hour": hour_tag, "grid": grid}, f)
            await r.delete(key)
        if cursor == 0:
            break


async def prune_snapshots() -> None:
    settings = get_settings()
    cutoff = time.time() - settings.retention_snapshots_days * 86400
    base = os.path.join(settings.media_root, "snapshots")
    if not os.path.isdir(base):
        return
    removed = 0
    for day_dir in os.listdir(base):
        full = os.path.join(base, day_dir)
        if not os.path.isdir(full):
            continue
        for name in os.listdir(full):
            path = os.path.join(full, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
        if not os.listdir(full):
            os.rmdir(full)
    if removed:
        log.info("pruned %d expired snapshots", removed)


async def cleanup_stuck_uploads() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(sa.text(
            "UPDATE upload_jobs SET status = 'error', error = 'timed out' "
            "WHERE status = 'processing' AND created_at < now() - INTERVAL '6 hours'"
        ))


async def run_daily_rollup(day: dt.date | None = None) -> None:
    day = day or (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=1))
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(DAILY_ROLLUP, {"day": day})


async def run_hourly_aggregation_loop(stop_event: asyncio.Event) -> None:
    last_heatmap_hour = -1
    while not stop_event.is_set():
        try:
            await aggregate_current_hour()
            hour = dt.datetime.now(dt.UTC).hour
            if hour != last_heatmap_hour:
                last_heatmap_hour = hour
                await snapshot_heatmaps()
        except Exception:
            log.exception("hourly aggregation failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=AGGREGATION_INTERVAL)
        except TimeoutError:
            pass


async def run_nightly_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        now = dt.datetime.now(dt.UTC)
        next_run = (now + dt.timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
        try:
            await asyncio.wait_for(stop_event.wait(),
                                   timeout=(next_run - now).total_seconds())
            return
        except TimeoutError:
            pass
        try:
            await run_daily_rollup()
            await prune_snapshots()
            await cleanup_stuck_uploads()
            log.info("nightly maintenance complete")
        except Exception:
            log.exception("nightly maintenance failed")
