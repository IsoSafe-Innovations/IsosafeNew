import datetime as dt
import json
import os

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import CurrentUser, require_viewer
from app.config import get_settings
from app.db.engine import get_engine
from app.db.tables import analytics_hourly, incidents
from app.redis_client import COUNTS_KEY, get_redis

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats/{camera_id}")
async def camera_stats(
    camera_id: str,
    hours: int = Query(24, ge=1, le=24 * 30),
    user: CurrentUser = Depends(require_viewer),
) -> dict:
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    engine = get_engine()
    async with engine.connect() as conn:
        if camera_id == "all":
            query = (
                sa.select(
                    analytics_hourly.c.bucket,
                    sa.func.sum(analytics_hourly.c.footfall).label("footfall"),
                    sa.func.avg(analytics_hourly.c.avg_queue).label("avg_queue"),
                    sa.func.max(analytics_hourly.c.max_queue).label("max_queue"),
                    sa.func.avg(analytics_hourly.c.avg_occupancy).label("avg_occupancy"),
                    sa.func.sum(analytics_hourly.c.incident_count).label("incident_count"),
                )
                .where(analytics_hourly.c.bucket >= since)
                .group_by(analytics_hourly.c.bucket)
                .order_by(analytics_hourly.c.bucket)
            )
            rows = (await conn.execute(query)).mappings().all()
            buckets = [
                {
                    "bucket": r["bucket"].isoformat(),
                    "footfall": int(r["footfall"] or 0),
                    "vehicles": {},
                    "avg_queue": float(r["avg_queue"] or 0),
                    "max_queue": int(r["max_queue"] or 0),
                    "avg_occupancy": float(r["avg_occupancy"] or 0),
                    "incident_count": int(r["incident_count"] or 0),
                }
                for r in rows
            ]
        else:
            query = (
                sa.select(analytics_hourly)
                .where(
                    analytics_hourly.c.camera_id == camera_id,
                    analytics_hourly.c.bucket >= since,
                )
                .order_by(analytics_hourly.c.bucket)
            )
            rows = (await conn.execute(query)).mappings().all()
            buckets = [
                {**dict(r), "bucket": r["bucket"].isoformat()} for r in rows
            ]
    return {"camera_id": camera_id, "hours": hours, "buckets": buckets}


@router.get("/counts")
async def live_counts(user: CurrentUser = Depends(require_viewer)) -> dict:
    """Live per-camera session counts straight from Redis."""
    raw = await get_redis().hgetall(COUNTS_KEY)
    return {cid: json.loads(v) for cid, v in raw.items()}


@router.get("/heatmap/{camera_id}")
async def heatmap(camera_id: str, user: CurrentUser = Depends(require_viewer)) -> dict:
    path = os.path.join(get_settings().media_root, "heatmaps", f"{camera_id}_latest.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="No heatmap yet for this camera")
    with open(path) as f:
        return json.load(f)


@router.get("/overview")
async def overview(user: CurrentUser = Depends(require_viewer)) -> dict:
    """Dashboard KPIs for today, with deltas versus yesterday."""
    now = dt.datetime.now(dt.timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - dt.timedelta(days=1)

    engine = get_engine()
    async with engine.connect() as conn:
        async def window(start, end):
            row = (
                await conn.execute(
                    sa.select(
                        sa.func.coalesce(sa.func.sum(analytics_hourly.c.footfall), 0),
                        sa.func.coalesce(sa.func.avg(analytics_hourly.c.avg_occupancy), 0.0),
                        sa.func.coalesce(sa.func.sum(analytics_hourly.c.incident_count), 0),
                    ).where(
                        analytics_hourly.c.bucket >= start,
                        analytics_hourly.c.bucket < end,
                    )
                )
            ).one()
            vehicles = (
                await conn.execute(
                    sa.text(
                        "SELECT COALESCE(SUM(value::int), 0) FROM analytics_hourly, "
                        "jsonb_each_text(vehicles) WHERE bucket >= :s AND bucket < :e"
                    ),
                    {"s": start, "e": end},
                )
            ).scalar_one()
            return {
                "footfall": int(row[0]),
                "avg_occupancy": round(float(row[1]), 1),
                "incidents": int(row[2]),
                "vehicles": int(vehicles),
            }

        today = await window(today_start, now)
        yesterday = await window(yesterday_start, today_start)

        open_incidents = (
            await conn.execute(
                sa.select(sa.func.count()).select_from(incidents).where(
                    incidents.c.status.in_(["open", "investigating"])
                )
            )
        ).scalar_one()
        suspicious = (
            await conn.execute(
                sa.select(sa.func.count()).select_from(incidents).where(
                    incidents.c.ts >= today_start,
                    incidents.c.severity.in_(["warning", "critical"]),
                )
            )
        ).scalar_one()

    return {
        "today": today,
        "yesterday": yesterday,
        "open_incidents": int(open_incidents),
        "suspicious_today": int(suspicious),
    }
