"""Agent incident API unit tests: payload shape, UUID idempotency key, presigning.

DB-backed upsert/idempotency integration tests arrive with the Day 5 agent API
suite; here we cover the pieces that do not need Postgres.
"""
import datetime as dt
import json
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.api import agent as agent_api
from app.api.types import AgentIncidentIn, normalize_severity
from app.config import get_settings
from app.storage import snapshot_key

VALID_UUID = "12345678-1234-5678-1234-567812345678"


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request(
        {"type": "http", "method": "POST", "path": "/agent/v1/incidents", "headers": raw}
    )


def test_snapshot_key_matches_prd_layout():
    ts = dt.datetime(2026, 10, 9, 13, 5, tzinfo=dt.UTC)
    assert snapshot_key(VALID_UUID, ts) == f"snapshots/2026/10/09/{VALID_UUID}.jpg"


def test_snapshot_key_accepts_epoch_float():
    ts = dt.datetime(2026, 1, 2, 3, 4, tzinfo=dt.UTC).timestamp()
    assert snapshot_key("abc", ts) == "snapshots/2026/01/02/abc.jpg"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("high", "critical"),
        ("critical", "critical"),
        ("medium", "warning"),
        ("warning", "warning"),
        ("low", "info"),
        ("nonsense", "warning"),
        (None, "warning"),
    ],
)
def test_normalize_severity(raw, expected):
    assert normalize_severity(raw) == expected


def test_agent_payload_accepts_prd_example():
    payload = AgentIncidentIn.model_validate(
        {
            "uuid": VALID_UUID,
            "camera_id": "cam-1",
            "rule_id": "loiter-stockroom",
            "type": "loitering",
            "severity": "high",
            "ts": 1760000000.123,
            "details": {"description": "Person loitering for 32s"},
            "has_snapshot": True,
        }
    )
    assert str(payload.uuid) == VALID_UUID
    assert payload.has_snapshot is True


def test_agent_payload_requires_uuid():
    with pytest.raises(ValidationError):
        AgentIncidentIn.model_validate({"camera_id": "cam-1", "type": "loitering"})


def test_agent_payload_rejects_bad_uuid():
    with pytest.raises(ValidationError):
        AgentIncidentIn.model_validate(
            {"uuid": "not-a-uuid", "camera_id": "cam-1", "type": "loitering"}
        )


def test_agent_auth_rejects_missing_and_wrong_token(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "1")
    monkeypatch.setenv("AGENT_TOKEN", "correct-token")
    get_settings.cache_clear()
    try:
        with pytest.raises(HTTPException) as missing:
            agent_api._require_agent_auth(_request({}))
        assert missing.value.status_code == 401

        with pytest.raises(HTTPException) as wrong:
            agent_api._require_agent_auth(_request({"authorization": "Bearer nope"}))
        assert wrong.value.status_code == 401

        agent_api._require_agent_auth(_request({"authorization": "Bearer correct-token"}))
    finally:
        get_settings.cache_clear()


def test_agent_auth_forbidden_when_mode_off(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "0")
    monkeypatch.setenv("AGENT_TOKEN", "correct-token")
    get_settings.cache_clear()
    try:
        with pytest.raises(HTTPException) as exc:
            agent_api._require_agent_auth(_request({"authorization": "Bearer correct-token"}))
        assert exc.value.status_code == 403
    finally:
        get_settings.cache_clear()


async def test_publish_incident_alert_uses_existing_alert_shape(monkeypatch):
    captured: list[tuple[str, str]] = []

    class FakeRedis:
        async def publish(self, channel: str, data: str) -> None:
            captured.append((channel, data))

    monkeypatch.setattr(agent_api, "get_redis", lambda: FakeRedis())
    monkeypatch.setattr(agent_api, "resolve_snapshot_url", lambda path: "https://signed/get.jpg")

    await agent_api._publish_incident_alert(
        7,
        VALID_UUID,
        "cam-1",
        "loitering",
        "critical",
        "Person loitering",
        f"snapshots/2026/10/09/{VALID_UUID}.jpg",
        dt.datetime(2026, 10, 9, tzinfo=dt.UTC),
    )

    channel, data = captured[0]
    assert channel == agent_api.ALERT_CHANNEL
    payload = json.loads(data)
    assert payload["type"] == "incident"
    assert payload["id"] == 7
    assert payload["uuid"] == VALID_UUID
    assert payload["snapshot_url"] == "https://signed/get.jpg"


def test_presigned_put_and_get_urls(monkeypatch):
    pytest.importorskip("boto3")
    monkeypatch.setenv("S3_BUCKET", "isosafe-snapshots")
    monkeypatch.setenv("S3_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("S3_SECRET_KEY", "minioadmin")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setenv("S3_PUBLIC_ENDPOINT_URL", "http://localhost:9000")
    get_settings.cache_clear()
    try:
        from app.storage import presigned_get_url, presigned_put_url

        key = f"snapshots/2026/10/09/{uuid.uuid4()}.jpg"
        put = presigned_put_url(key)
        get = presigned_get_url(key)
        assert put and "X-Amz-Signature" in put and key in put
        assert get and "X-Amz-Signature" in get and key in get
    finally:
        get_settings.cache_clear()
