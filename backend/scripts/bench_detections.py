"""Phase 3 acceptance: insert 1M synthetic detections, time an hourly range query.

Usage: python -m scripts.bench_detections
"""
import asyncio
import datetime as dt
import random
import time

from app.db.engine import get_asyncpg_pool

ROWS = 1_000_000
BATCH = 10_000
CAMERAS = [f"cam-{i:02d}" for i in range(16)]
OBJECTS = ["person", "car", "truck", "bus", "motorcycle"]

INSERT = """
INSERT INTO detections (camera_id, ts, object_type, confidence, track_id, bbox, zone_ids)
VALUES ($1, $2, $3, $4, $5, $6, $7)
"""


async def main() -> None:
    pool = await get_asyncpg_pool()
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=7)
    span = (now - start).total_seconds()

    t0 = time.monotonic()
    inserted = 0
    async with pool.acquire() as conn:
        while inserted < ROWS:
            rows = []
            for _ in range(min(BATCH, ROWS - inserted)):
                ts = start + dt.timedelta(seconds=random.random() * span)
                x1, y1 = random.random() * 0.8, random.random() * 0.8
                rows.append((
                    random.choice(CAMERAS), ts, random.choice(OBJECTS),
                    round(random.uniform(0.35, 0.99), 3), random.randint(1, 99999),
                    [x1, y1, x1 + 0.15, y1 + 0.25],
                    ["zone-a"] if random.random() < 0.3 else None,
                ))
            await conn.executemany(INSERT, rows)
            inserted += len(rows)
            print(f"  inserted {inserted:,}", flush=True)
    insert_secs = time.monotonic() - t0
    print(f"Inserted {ROWS:,} rows in {insert_secs:.1f}s "
          f"({ROWS / insert_secs:,.0f} rows/sec)")

    query = """
        SELECT date_trunc('hour', ts) AS bucket, object_type, COUNT(*)
        FROM detections
        WHERE camera_id = $1 AND ts >= $2 AND ts < $3
        GROUP BY 1, 2 ORDER BY 1
    """
    q_start = now - dt.timedelta(hours=24)
    async with pool.acquire() as conn:
        await conn.fetch(query, "cam-05", q_start, now)  # warm
        t0 = time.monotonic()
        rows = await conn.fetch(query, "cam-05", q_start, now)
        elapsed_ms = (time.monotonic() - t0) * 1000
    print(f"Hourly range query: {len(rows)} groups in {elapsed_ms:.1f}ms "
          f"({'PASS' if elapsed_ms < 100 else 'FAIL'} <100ms target)")


if __name__ == "__main__":
    asyncio.run(main())
