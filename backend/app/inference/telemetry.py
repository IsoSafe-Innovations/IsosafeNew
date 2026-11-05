"""Analysis progress, deliberately separate from ingestion and browser playback."""
import json
import time
from collections import deque

from app.redis_client import get_redis

ANALYSIS_KEY_PREFIX = "isosafe:analysis:"


class AnalysisTelemetry:
    def __init__(self, camera_id, options):
        self.camera_id = camera_id
        self.options = options
        self.state = "warming_up"
        self.error = None
        self.last_result_ts = None
        self.frame_ts = None
        self.inference_ms = None
        self.processed = 0
        self._times = deque(maxlen=300)
        self._last_flush = 0
        self.dropped = 0
        self.queue_depth = 0
        self.ocr_state = "idle"
        self.crossings = {}

    def snapshot(self):
        now = time.time()
        recent = [t for t in self._times if now-t < 10]
        fps = (len(recent)-1)/(recent[-1]-recent[0]) if len(recent)>1 and recent[-1]>recent[0] else 0
        return {"state": self.state, "error": self.error, "last_result_ts": self.last_result_ts,
                "frame_ts": self.frame_ts, "processed_fps": round(fps,2), "processed_frames": self.processed,
                "inference_ms": self.inference_ms, "dropped_frames": self.dropped,
                "queue_depth": self.queue_depth, "ocr_state": self.ocr_state,
                "preset": self.options.get("preset", "fast"), "tracker": self.options.get("tracker", "centroid"),
                "crossings": dict(self.crossings), "_processed_times": recent}

    async def flush(self, force=False):
        now = time.time()
        if not force and now-self._last_flush < 1:
            return
        self._last_flush = now
        try:
            await get_redis().set(ANALYSIS_KEY_PREFIX+self.camera_id, json.dumps(self.snapshot()), ex=180)
        except Exception:
            # Agent heartbeats carry this same snapshot when no local Redis exists.
            pass

    async def record(self, frame_ts, inference_ms):
        now = time.time()
        self.last_result_ts, self.frame_ts = now, frame_ts
        self.inference_ms = round(inference_ms,1)
        self.processed += 1
        self._times.append(now)
        self.state, self.error = "running", None
        from app.metrics import ANALYSIS_FPS, ANALYSIS_FRAME_AGE
        ANALYSIS_FPS.labels(camera_id=self.camera_id).set(self.snapshot()["processed_fps"])
        ANALYSIS_FRAME_AGE.labels(camera_id=self.camera_id).set(max(0,now-frame_ts))
        await self.flush()


def present_analysis(value, now=None):
    now = time.time() if now is None else now
    out = dict(value or {"state": "waiting", "processed_fps": 0, "processed_frames": 0})
    last = out.get("last_result_ts")
    frame = out.get("frame_ts")
    recent=[t for t in out.pop("_processed_times",[]) if now-t < 10]
    if recent:
        out["processed_fps"] = round((len(recent)-1)/max(.001,now-recent[0]),2) if len(recent)>1 else 0
    out["result_age_secs"] = round(max(0,now-last),1) if last else None
    out["frame_age_secs"] = round(max(0,now-frame),1) if frame else None
    if out.get("state") == "running" and (not last or now-last > 15):
        out["state"] = "stalled"
        out["processed_fps"] = 0
    elif out.get("state") == "running" and frame and now-frame > 3:
        out["state"] = "delayed"
    out["ready"] = out.get("state") in {"running", "delayed"}
    return out


async def read_analysis(camera_ids):
    if not camera_ids:
        return {}
    values = await get_redis().mget([ANALYSIS_KEY_PREFIX+cid for cid in camera_ids])
    return {cid: present_analysis(json.loads(value) if value else None) for cid,value in zip(camera_ids,values)}
