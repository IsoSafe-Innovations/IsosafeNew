import redis.asyncio as aioredis

from app.config import get_settings

_client: aioredis.Redis | None = None

ALERT_CHANNEL = "isosafe:alerts"
FRAME_CHANNEL = "isosafe:frames"
COUNTS_KEY = "isosafe:counts"  # hash camera_id -> json counts
HEALTH_KEY_PREFIX = "isosafe:camera_health:"
HEATMAP_KEY_PREFIX = "isosafe:heatmap:"
INSIGHTS_CACHE_KEY = "isosafe:insights"


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
