import logging

import sqlalchemy as sa
from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.db.engine import get_engine
from app.redis_client import get_redis

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict:
    db_ok = redis_ok = False
    db_error = redis_error = None
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        db_ok = True
    except Exception as e:
        db_error = str(e)
    try:
        await get_redis().ping()
        redis_ok = True
    except Exception as e:
        redis_error = str(e)

    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "database": {"ok": db_ok, "error": db_error},
        "redis": {"ok": redis_ok, "error": redis_error},
    }


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
