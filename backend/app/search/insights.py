"""AI insights: hourly task sends the last 24h of analytics_hourly plus open
incidents to Claude, asks for 3-6 actionable observations, caches in Redis."""
import datetime as dt
import json
import logging

import sqlalchemy as sa

from app.config import get_settings
from app.db.engine import get_engine
from app.db.tables import analytics_hourly, incidents
from app.redis_client import INSIGHTS_CACHE_KEY, get_redis

log = logging.getLogger(__name__)

INSIGHTS_PROMPT = """You are the analytics brain of a building CCTV intelligence platform.
Given the last 24 hours of per-camera hourly metrics and the currently open incidents,
produce 3 to 6 short, actionable observations for the operations manager: staffing
suggestions, risk windows, recurring patterns, anomalies worth checking.

Respond with ONLY a JSON array of objects: [{"title": "...", "detail": "...", "kind": "staffing|risk|pattern|anomaly"}]"""


async def _collect_context() -> dict:
    since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=24)
    engine = get_engine()
    async with engine.connect() as conn:
        hourly = (
            await conn.execute(
                sa.select(analytics_hourly)
                .where(analytics_hourly.c.bucket >= since)
                .order_by(analytics_hourly.c.bucket)
            )
        ).mappings().all()
        open_inc = (
            await conn.execute(
                sa.select(
                    incidents.c.camera_id, incidents.c.ts, incidents.c.incident_type,
                    incidents.c.severity, incidents.c.description, incidents.c.status,
                ).where(incidents.c.status.in_(["open", "investigating"]))
                .order_by(incidents.c.ts.desc()).limit(50)
            )
        ).mappings().all()
    return {
        "hourly": [
            {**dict(r), "bucket": r["bucket"].isoformat()} for r in hourly
        ],
        "open_incidents": [
            {**dict(r), "ts": r["ts"].isoformat()} for r in open_inc
        ],
    }


async def generate_insights() -> list[dict]:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return []

    import anthropic

    context = await _collect_context()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1500,
        system=INSIGHTS_PROMPT,
        messages=[{"role": "user", "content": json.dumps(context, default=str)}],
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        insights = json.loads(text)
        if not isinstance(insights, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        log.warning("insights response was not a JSON array")
        return []

    payload = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "insights": insights,
    }
    await get_redis().set(INSIGHTS_CACHE_KEY, json.dumps(payload), ex=86400)
    return insights


async def get_cached_insights() -> dict | None:
    raw = await get_redis().get(INSIGHTS_CACHE_KEY)
    return json.loads(raw) if raw else None
