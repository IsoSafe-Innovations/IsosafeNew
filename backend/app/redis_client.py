import redis.asyncio as aioredis

from app.config import get_settings

_client: aioredis.Redis | None = None

ALERT_CHANNEL = "isosafe:alerts"
FRAME_CHANNEL = "isosafe:frames"
COUNTS_KEY = "isosafe:counts"  # hash camera_id -> json counts
HEALTH_KEY_PREFIX = "isosafe:camera_health:"
HEATMAP_KEY_PREFIX = "isosafe:heatmap:"
INSIGHTS_CACHE_KEY = "isosafe:insights"
AGENT_LAST_SEEN_KEY = "agent:last_seen"
AGENT_HEALTH_KEY = "agent:health"


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        try:
            _client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        except Exception:
            _client = aioredis.from_url("redis://localhost:6379/0", decode_responses=True)
    return _client

async def close_redis() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None
