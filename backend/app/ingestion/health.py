"""Per-camera health tracked in Redis: last frame ts, reconnects, FPS, drops."""
import json
import time
from dataclasses import dataclass, field

from app.metrics import CAMERA_FPS, STREAM_RECONNECTS
from app.redis_client import HEALTH_KEY_PREFIX, get_redis


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
        r = get_redis()
        await r.set(HEALTH_KEY_PREFIX + self.camera_id, json.dumps(payload), ex=120)


async def read_all_health(camera_ids: list[str]) -> dict[str, dict]:
    r = get_redis()
    out: dict[str, dict] = {}
    if not camera_ids:
        return out
    keys = [HEALTH_KEY_PREFIX + cid for cid in camera_ids]
    values = await r.mget(keys)
    for cid, raw in zip(camera_ids, values):
        if raw:
            data = json.loads(raw)
            data["online"] = (time.time() - data.get("last_frame_ts", 0)) < 30
            out[cid] = data
        else:
            out[cid] = {"online": False, "fps": 0, "reconnect_count": 0, "frames_dropped": 0}
    return out
