"""Agent API transport-level tests: auth on every endpoint, /media lockdown,
oversized-request rejection, and the live-stream WebSocket.

These exercise the real FastAPI routes with a TestClient so the PRD checklist
(valid token -> 200, missing/wrong -> 401, >1MB -> reject, /media -> 404) is
covered end to end without Postgres/Redis/S3.
"""
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import agent as agent_api
from app.config import get_settings
from app.main import create_app

VALID_UUID = "12345678-1234-5678-1234-567812345678"
TOKEN = "correct-agent-token"


@pytest.fixture
def agent_env(monkeypatch, tmp_path):
    """Enable agent mode with a real media dir, so /media *would* mount if allowed."""
    media = tmp_path / "media"
    media.mkdir()
    (media / "leak.jpg").write_bytes(b"should-not-be-served")
    monkeypatch.setenv("AGENT_MODE", "1")
    monkeypatch.setenv("AGENT_TOKEN", TOKEN)
    monkeypatch.setenv("MEDIA_ROOT", str(media))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(agent_env):
    return TestClient(create_app())


# --- fake DB / Redis so handlers run without infra ---


class _Result:
    def mappings(self):
        return self

    def all(self):
        return []

    def first(self):
        return (1,)

    def scalar_one(self):
        return 1


class _Conn:
    async def execute(self, *args, **kwargs):
        return _Result()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeEngine:
    def connect(self):
        return _Conn()

    def begin(self):
        return _Conn()


class _FakeRedis:
    def __init__(self):
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel, data):
        self.published.append((channel, data))


class _LimiterRedis:
    """Rate-limiter stand-in for app.api.deps (no Redis in tests)."""

    def __init__(self, count: int = 1):
        self.count = count

    async def incr(self, key):
        return self.count

    async def expire(self, key, ttl):
        return True


@pytest.fixture(autouse=True)
def fake_limiter_redis(monkeypatch):
    """The /agent/v1 limiter uses deps.get_redis; give it an allowing fake."""
    monkeypatch.setattr("app.api.deps.get_redis", lambda: _LimiterRedis())


@pytest.fixture
def patched_backends(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(agent_api, "get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(agent_api, "get_redis", lambda: redis)
    monkeypatch.setattr(agent_api, "presigned_put_url", lambda key: "https://signed/put.jpg")
    return redis


# --- constant-time comparison ---


def test_token_comparison_is_constant_time(monkeypatch, agent_env):
    calls: list[tuple[str, str]] = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(agent_api.hmac, "compare_digest", spy)

    req = _request({"authorization": f"Bearer {TOKEN}"})
    agent_api._require_agent_auth(req)
    assert calls, "agent auth must use hmac.compare_digest (constant-time)"


def _request(headers: dict[str, str]):
    from starlette.requests import Request

    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/agent/v1/config", "headers": raw})


# --- auth on every HTTP endpoint: 200 / 401 / 401 ---

_AUTH_CASES = [
    ("/agent/v1/config", "get", None),
    ("/agent/v1/incidents", "post", {
        "uuid": VALID_UUID, "camera_id": "cam-1", "type": "loitering", "severity": "high",
    }),
    ("/agent/v1/heartbeat", "post", {"agent_version": "1.0-agent", "cameras": []}),
]


@pytest.mark.parametrize("path,method,body", _AUTH_CASES)
def test_endpoint_missing_token_401(client, path, method, body):
    resp = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
    assert resp.status_code == 401


@pytest.mark.parametrize("path,method,body", _AUTH_CASES)
def test_endpoint_wrong_token_401(client, path, method, body):
    headers = {"Authorization": "Bearer wrong-token"}
    resp = getattr(client, method)(path, json=body, headers=headers) if body is not None else getattr(client, method)(path, headers=headers)
    assert resp.status_code == 401


def test_config_valid_token_200(client, patched_backends):
    r = client.get("/agent/v1/config", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json() == {"config_version": r.json()["config_version"], "cameras": []}


def test_config_returns_decrypted_usable_source(client, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    from app.security import encrypt_source

    row = {
        "id": "cam-1", "name": "Front", "source": encrypt_source("rtsp://u:p@10.0.0.5/s1"),
        "type": "rtsp", "vertical_profile": None, "zones": [], "rules": [],
        "refresh_secs": 2.0, "loop_file": True, "enabled": True, "created_at": None,
    }

    class _Rows:
        def mappings(self):
            return self

        def all(self):
            return [row]

    class _Conn:
        async def execute(self, *a, **k):
            return _Rows()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

    class _Engine:
        def connect(self):
            return _Conn()

    monkeypatch.setattr(agent_api, "get_engine", lambda: _Engine())
    r = client.get("/agent/v1/config", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json()["cameras"][0]["source"] == "rtsp://u:p@10.0.0.5/s1"


def test_incidents_valid_token_200(client, patched_backends):
    body = {
        "uuid": VALID_UUID, "camera_id": "cam-1", "type": "loitering",
        "severity": "high", "ts": 1760000000.0, "has_snapshot": True,
    }
    r = client.post("/agent/v1/incidents", json=body, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json()["incident_id"] == 1
    assert "snapshot_put_url" in r.json()


class _NoRow:
    def first(self):
        return None

    def mappings(self):
        return self

    def one(self):
        raise AssertionError("unexpected")


class _ConflictConn:
    """First upsert misses (unique violation), follow-up select finds the row."""

    def __init__(self):
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _NoRow()
        self.existing = {"id": 7, "snapshot_path": "snapshots/2026/10/09/original.jpg"}
        return self

    def mappings(self):
        return self

    def one(self):
        return self.existing


class _ConflictEngine:
    def begin(self):
        return _ConflictConn()

    def connect(self):
        return _ConflictConn()


def test_incidents_duplicate_uuid_is_idempotent(client, monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(agent_api, "get_engine", lambda: _ConflictEngine())
    monkeypatch.setattr(agent_api, "get_redis", lambda: redis)
    monkeypatch.setattr(agent_api, "presigned_put_url", lambda key: f"https://signed/{key}")
    body = {
        "uuid": VALID_UUID, "camera_id": "cam-1", "type": "loitering",
        "severity": "high", "ts": 1760000000.0, "has_snapshot": False,
    }
    r = client.post("/agent/v1/incidents", json=body, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json()["duplicate"] is True
    assert r.json()["incident_id"] == 7
    # Original snapshot key is preserved for the retry's PUT.
    assert "snapshots/2026/10/09/original.jpg" in r.json()["snapshot_put_url"]
    # A replay must not fan out a second alert.
    assert redis.published == []


def test_heartbeat_valid_token_204(client, monkeypatch):
    seen: list[dict] = []

    async def fake_store(payload):
        seen.append(payload)

    monkeypatch.setattr(agent_api, "store_heartbeat", fake_store)
    r = client.post(
        "/agent/v1/heartbeat",
        json={"agent_version": "1.0-agent", "uptime_s": 10, "cameras": []},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 204
    assert seen and seen[0]["agent_version"] == "1.0-agent"


# --- DEMO-FR-27: /agent/v1 HTTP endpoints are rate-limited ---


def test_agent_endpoint_rate_limited_429(client, monkeypatch):
    monkeypatch.setattr("app.api.deps.get_redis", lambda: _LimiterRedis(count=601))
    r = client.get("/agent/v1/config", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 429


# --- oversized request (>1MB) is rejected before parsing ---


def test_oversized_request_rejected_413(client):
    big = {"uuid": VALID_UUID, "camera_id": "cam-1", "type": "loitering", "blob": "x" * (1024 * 1024)}
    r = client.post(
        "/agent/v1/incidents", json=big, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert r.status_code == 413


def _chunked(payload: bytes, chunk: int = 65536):
    for i in range(0, len(payload), chunk):
        yield payload[i:i + chunk]


def test_chunked_oversized_request_rejected_413(client):
    # No Content-Length: the cap must still be enforced while streaming.
    payload = (
        b'{"uuid":"' + VALID_UUID.encode() + b'","camera_id":"cam-1","type":"loitering","blob":"'
        + b"x" * (1024 * 1024) + b'"}'
    )
    r = client.post(
        "/agent/v1/incidents",
        content=_chunked(payload),
        headers={"Authorization": f"Bearer {TOKEN}", "Transfer-Encoding": "chunked"},
    )
    assert r.status_code == 413


def test_chunked_request_under_limit_is_replayed(client, monkeypatch):
    seen: list[dict] = []

    async def fake_store(data):
        seen.append(data)

    monkeypatch.setattr(agent_api, "store_heartbeat", fake_store)
    r = client.post(
        "/agent/v1/heartbeat",
        content=_chunked(json.dumps({"agent_version": "1.0-agent", "cameras": []}).encode()),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Transfer-Encoding": "chunked",
            "Content-Type": "application/json",
        },
    )
    assert r.status_code == 204
    assert seen and seen[0]["agent_version"] == "1.0-agent"


# --- old public /media route must 404 on staging ---


def test_media_route_404_in_agent_mode(client):
    assert client.get("/media/leak.jpg").status_code == 404


def test_media_route_served_when_not_agent_mode(monkeypatch, tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "ok.jpg").write_bytes(b"served")
    monkeypatch.setenv("AGENT_MODE", "0")
    monkeypatch.setenv("MEDIA_ROOT", str(media))
    get_settings.cache_clear()
    try:
        c = TestClient(create_app())
        assert c.get("/media/ok.jpg").status_code == 200
    finally:
        get_settings.cache_clear()


# --- live stream WebSocket auth + frame republish ---


def test_stream_ws_rejects_wrong_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/agent/v1/stream?token=nope"):
            pass


def test_stream_ws_rejects_missing_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/agent/v1/stream"):
            pass


def test_stream_ws_accepts_and_republishes_frame(client, patched_backends):
    frame = json.dumps({"type": "frame", "camera_id": "cam-1", "image": "abc", "counts": {}})
    with client.websocket_connect(f"/agent/v1/stream?token={TOKEN}") as ws:
        assert ws.receive_json() == {"type": "hello"}
        ws.send_text(frame)
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json() == {"type": "pong"}

    assert patched_backends.published == [(agent_api.FRAME_CHANNEL, frame)]


def test_stream_ws_drops_oversized_message(client, patched_backends):
    oversized = json.dumps({"type": "frame", "camera_id": "cam-1", "image": "x" * (1024 * 1024)})
    with client.websocket_connect(f"/agent/v1/stream?token={TOKEN}") as ws:
        assert ws.receive_json() == {"type": "hello"}
        ws.send_text(oversized)
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json() == {"type": "pong"}

    assert patched_backends.published == []
