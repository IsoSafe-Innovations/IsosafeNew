"""Per-camera health tracked in Redis: last frame ts, reconnects, FPS, drops."""
import json
import logging
import time
from dataclasses import dataclass, field

from app.config import get_settings
from app.metrics import CAMERA_FPS, STREAM_RECONNECTS
from app.redis_client import (
    AGENT_HEALTH_KEY,
    AGENT_LAST_SEEN_KEY,
    HEALTH_KEY_PREFIX,
    get_redis,
)

log = logging.getLogger(__name__)


@dataclass
class CameraHealth:
    camera_id: str
    frames_dropped: int = 0
    reconnect_count: int = 0
    _frame_times: list[float] = field(default_factory=list)
    _last_flush: float = 0.0

    async def record_frame(self) -> None:
        now = time.time()
        self._frame_times.append(now)
        cutoff = now - 10.0
        self._frame_times = [t for t in self._frame_times if t >= cutoff]
        if now - self._last_flush >= 2.0:
            await self._flush(now)

    async def record_reconnect(self) -> None:
        self.reconnect_count += 1
        STREAM_RECONNECTS.labels(camera_id=self.camera_id).inc()
        await self._flush(time.time())

    @property
    def fps(self) -> float:
        if len(self._frame_times) < 2:
            return 0.0
        span = self._frame_times[-1] - self._frame_times[0]
        return round((len(self._frame_times) - 1) / span, 2) if span > 0 else 0.0

    async def _flush(self, now: float) -> None:
        self._last_flush = now
        CAMERA_FPS.labels(camera_id=self.camera_id).set(self.fps)
        payload = {
            "last_frame_ts": now,
            "reconnect_count": self.reconnect_count,
            "fps": self.fps,
            "frames_dropped": self.frames_dropped,
        }
        # Best-effort: an on-site agent keeps no Redis (PRD v2 Phase 1a), and a
        # cloud Redis blip must never drop the local stream. Health still reaches
        # the dashboard via the agent heartbeat; only the direct cache is skipped.
        try:
            await get_redis().set(HEALTH_KEY_PREFIX + self.camera_id, json.dumps(payload), ex=120)
        except Exception:
            log.debug("camera health flush failed", exc_info=True)


async def read_all_health(camera_ids: list[str]) -> dict[str, dict]:
    r = get_redis()
    out: dict[str, dict] = {}
    if not camera_ids:
        return out
    keys = [HEALTH_KEY_PREFIX + cid for cid in camera_ids]
    values = await r.mget(keys)
    now = time.time()
    for cid, raw in zip(camera_ids, values):
        if raw:
            data = json.loads(raw)
            if data.get("source") == "agent":
                # Heartbeats carry an explicit per-camera online flag; the
                # agent only marks a camera offline when its stream is stopped.
                age = now - data.get("last_frame_ts", 0)
                data["online"] = bool(data.get("online", True)) and age < 180
            else:
                data["online"] = (now - data.get("last_frame_ts", 0)) < 30
            out[cid] = data
        else:
            out[cid] = {"online": False, "fps": 0, "reconnect_count": 0, "frames_dropped": 0}
    return out


async def store_heartbeat(payload: dict) -> None:
    """Persist an agent heartbeat: liveness key plus per-camera health."""
    now = time.time()
    r = get_redis()
    stored = {**payload, "received_at": now}
    pipe = r.pipeline(transaction=False)
    pipe.set(AGENT_LAST_SEEN_KEY, str(now))
    pipe.set(AGENT_HEALTH_KEY, json.dumps(stored))
    for cam in payload.get("cameras") or []:
        cid = cam.get("camera_id")
        if not cid:
            continue
        cam_health = {
            "last_frame_ts": now,
            "fps": cam.get("fps", 0.0),
            "reconnect_count": cam.get("reconnects", 0),
            "frames_dropped": cam.get("dropped", 0),
            "online": bool(cam.get("online", False)),
            "source": "agent",
        }
        pipe.set(HEALTH_KEY_PREFIX + cid, json.dumps(cam_health), ex=180)
    await pipe.execute()


async def read_agent_health() -> dict | None:
    """Return the latest agent heartbeat with a computed online flag."""
    r = get_redis()
    raw = await r.get(AGENT_HEALTH_KEY)
    last = await r.get(AGENT_LAST_SEEN_KEY)
    if not raw or not last:
        return {"online": False, "last_seen_ago": None}
    try:
        data = json.loads(raw)
        age = time.time() - float(last)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"online": False, "last_seen_ago": None}
    data["online"] = age <= get_settings().agent_online_secs
    data["last_seen_ago"] = round(age, 1)
    return data
