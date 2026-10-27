"""Agent live-stream + heartbeat unit tests (no Postgres/Redis required)."""
import base64
import json
import time
from types import SimpleNamespace

import numpy as np
import pytest

from app.agent import runtime
from app.agent.client import STREAM_BACKOFF, AgentClient
from app.api import agent as agent_api
from app.config import get_settings
from app.ingestion import health as health_mod
from app.redis_client import AGENT_HEALTH_KEY, AGENT_LAST_SEEN_KEY, HEALTH_KEY_PREFIX

ONE_MB = 1_048_576


class FakePipe:
    def __init__(self, store: dict):
        self.store = store
        self.ops = []

    def set(self, key, value, ex=None):
        self.ops.append((key, value))

    async def execute(self):
        for key, value in self.ops:
            self.store[key] = value


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def pipeline(self, transaction=False):
        return FakePipe(self.store)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def mget(self, keys):
        return [self.store.get(k) for k in keys]


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(health_mod, "get_redis", lambda: fake)
    return fake


# --- stream message parsing (DEMO-FR-24/40) ---


def test_parse_valid_frame():
    raw = json.dumps({"type": "frame", "camera_id": "cam-1", "image": "abc"})
    kind, msg = agent_api.parse_agent_message(raw, ONE_MB)
    assert kind == agent_api.FRAME
    assert msg["camera_id"] == "cam-1"


@pytest.mark.parametrize("mtype", ["ping", "pong"])
def test_parse_ping_pong(mtype):
    kind, _ = agent_api.parse_agent_message(json.dumps({"type": mtype}), ONE_MB)
    assert kind == mtype


def test_parse_invalid_json_and_non_dict():
    assert agent_api.parse_agent_message("not-json", ONE_MB)[0] == agent_api.INVALID
    assert agent_api.parse_agent_message("[1, 2, 3]", ONE_MB)[0] == agent_api.INVALID


def test_parse_drops_oversized_message():
    raw = json.dumps({"type": "frame", "image": "x" * 10})
    assert agent_api.parse_agent_message(raw, 4) == (agent_api.OVERSIZE, None)


def test_legacy_frame_kind_not_invalid():
    # A frame message that carries counts alongside the image still classifies.
    raw = json.dumps({"type": "frame", "camera_id": "c", "counts": {"a": 1}})
    assert agent_api.parse_agent_message(raw, ONE_MB)[0] == agent_api.FRAME


# --- heartbeat storage and agent health (DEMO-FR-24/41) ---


async def test_store_heartbeat_writes_liveness_and_camera_health(fake_redis):
    payload = {
        "agent_version": "1.0-agent",
        "uptime_s": 12.5,
        "cpu": 4.0,
        "mem": 20.0,
        "disk_free_gb": 42.0,
        "cameras": [
            {"camera_id": "cam-1", "online": True, "fps": 2.0, "reconnects": 1, "dropped": 3}
        ],
    }
    await health_mod.store_heartbeat(payload)

    assert AGENT_LAST_SEEN_KEY in fake_redis.store
    stored = json.loads(fake_redis.store[AGENT_HEALTH_KEY])
    assert stored["agent_version"] == "1.0-agent"
    cam = json.loads(fake_redis.store[HEALTH_KEY_PREFIX + "cam-1"])
    assert cam["source"] == "agent"
    assert cam["reconnect_count"] == 1
    assert cam["frames_dropped"] == 3
    assert cam["online"] is True


async def test_read_agent_health_marks_online_then_offline(fake_redis, monkeypatch):
    monkeypatch.setenv("AGENT_ONLINE_SECS", "90")
    get_settings.cache_clear()
    try:
        fake_redis.store[AGENT_HEALTH_KEY] = json.dumps({"agent_version": "1.0-agent"})
        fake_redis.store[AGENT_LAST_SEEN_KEY] = str(time.time())
        online = await health_mod.read_agent_health()
        assert online["online"] is True
        assert online["last_seen_ago"] is not None

        fake_redis.store[AGENT_LAST_SEEN_KEY] = str(time.time() - 1000)
        offline = await health_mod.read_agent_health()
        assert offline["online"] is False
    finally:
        get_settings.cache_clear()


async def test_read_agent_health_missing_returns_offline(fake_redis):
    result = await health_mod.read_agent_health()
    assert result == {"online": False, "last_seen_ago": None}


async def test_read_all_health_respects_agent_online_flag(fake_redis):
    now = time.time()
    fake_redis.store[HEALTH_KEY_PREFIX + "cam-on"] = json.dumps(
        {"last_frame_ts": now, "online": True, "source": "agent", "fps": 2.0}
    )
    fake_redis.store[HEALTH_KEY_PREFIX + "cam-off"] = json.dumps(
        {"last_frame_ts": now, "online": False, "source": "agent", "fps": 0.0}
    )
    fake_redis.store[HEALTH_KEY_PREFIX + "cam-stale"] = json.dumps(
        {"last_frame_ts": now - 1000, "online": True, "source": "agent"}
    )
    out = await health_mod.read_all_health(["cam-on", "cam-off", "cam-stale"])
    assert out["cam-on"]["online"] is True
    assert out["cam-off"]["online"] is False
    assert out["cam-stale"]["online"] is False


async def test_read_all_health_local_source_uses_30s_window(fake_redis):
    fake_redis.store[HEALTH_KEY_PREFIX + "cam-fresh"] = json.dumps(
        {"last_frame_ts": time.time(), "fps": 5.0}
    )
    fake_redis.store[HEALTH_KEY_PREFIX + "cam-old"] = json.dumps(
        {"last_frame_ts": time.time() - 60, "fps": 0.0}
    )
    out = await health_mod.read_all_health(["cam-fresh", "cam-old"])
    assert out["cam-fresh"]["online"] is True
    assert out["cam-old"]["online"] is False


# --- heartbeat payload builder ---


def test_build_heartbeat_shape():
    class Health:
        fps = 2.5
        reconnect_count = 3
        frames_dropped = 1

    class Stream:
        health = Health()
        stopped = False

    payload = runtime.build_heartbeat({"cam-1": Stream()}, uptime_s=9.0)
    assert payload["agent_version"] == get_settings().agent_version
    assert payload["uptime_s"] == 9.0
    cam = payload["cameras"][0]
    assert cam == {
        "camera_id": "cam-1",
        "online": True,
        "fps": 2.5,
        "reconnects": 3,
        "dropped": 1,
    }


# --- agent WS client ---


def _client(cloud_url: str, token: str = "") -> AgentClient:
    client = AgentClient()
    client.settings = SimpleNamespace(cloud_url=cloud_url, agent_token=token)
    return client


def test_stream_url_https_becomes_wss_with_token():
    url = _client("https://cloud.example.com", "tok en")._stream_url()
    assert url.startswith("wss://cloud.example.com/agent/v1/stream?token=tok%20en")


def test_stream_url_http_becomes_ws():
    url = _client("http://localhost:8000/")._stream_url()
    assert url == "ws://localhost:8000/agent/v1/stream"


def test_stream_url_accepts_ws_scheme():
    url = _client("wss://cloud.example.com")._stream_url()
    assert url == "wss://cloud.example.com/agent/v1/stream"


def test_stream_backoff_caps_at_30():
    assert STREAM_BACKOFF[0] == 1
    assert STREAM_BACKOFF[-1] == 30
    assert list(STREAM_BACKOFF) == sorted(STREAM_BACKOFF)


# --- cloud frame sink builds the same payload as the local path ---


async def test_cloud_frame_sink_sends_frame_message(monkeypatch):
    captured: list[dict] = []

    class FakeAgentClient:
        async def send_frame(self, message):
            captured.append(message)

    monkeypatch.setattr("app.sinks.frames.get_agent_client", lambda: FakeAgentClient())

    from app.sinks.frames import CloudFrameSink

    track = SimpleNamespace(
        bbox=(0.1, 0.1, 0.5, 0.6), object_type="person", track_id=1, last_plate=None
    )
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    await CloudFrameSink().publish_frame(
        "cam-1", image, [track], 123.0, counts={"session": {}}, in_frame={"person": 1}
    )

    assert len(captured) == 1
    message = captured[0]
    assert message["type"] == "frame"
    assert message["camera_id"] == "cam-1"
    assert message["in_frame"] == {"person": 1}
    assert base64.b64decode(message["image"])
