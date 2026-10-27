"""Agent incident outbox: bounded at 500, retried across outages, no duplicates.

The cloud upserts by agent-owned UUID, so a replay after a lost response is
idempotent. Here we verify the agent-side queue behavior without a network.
"""
import asyncio

from app.agent import client as client_mod
from app.agent.client import AgentClient
from app.config import get_settings


def _client() -> AgentClient:
    return AgentClient()


async def test_outbox_is_bounded_at_500_and_sheds_oldest(monkeypatch):
    monkeypatch.setenv("AGENT_INCIDENT_QUEUE_MAX", "500")
    get_settings.cache_clear()
    try:
        c = _client()
        # Prevent the drain loop from racing the assertions.
        c._outbox_stop = asyncio.Event()
        c._outbox_stop.set()
        for i in range(600):
            c.queue_incident({"uuid": f"u{i}"}, None)
        assert c.outbox_depth() == 500
        assert c._outbox[0][0]["uuid"] == "u100"  # 100 oldest shed
        if c._outbox_task is not None:
            await c._outbox_task
    finally:
        get_settings.cache_clear()


async def test_outbox_retries_until_cloud_recovers(monkeypatch):
    monkeypatch.setattr(client_mod, "INCIDENT_BACKOFF", (0.01, 0.01, 0.01, 0.01))
    c = _client()
    attempts: list[str] = []
    sent: list[dict] = []

    async def flaky_post(payload):
        attempts.append(payload["uuid"])
        if len(attempts) < 3:
            raise RuntimeError("cloud down")
        sent.append(payload)
        return {"incident_id": 1, "snapshot_put_url": None, "duplicate": False}

    monkeypatch.setattr(c, "_post_incident", flaky_post)

    c.queue_incident({"uuid": "u1"}, None)
    for _ in range(500):
        if c.outbox_depth() == 0:
            break
        await asyncio.sleep(0.01)

    assert c.outbox_depth() == 0
    assert attempts == ["u1", "u1", "u1"]  # retried, single logical incident
    assert sent == [{"uuid": "u1"}]
    await c.stop_outbox()


async def test_outbox_stops_when_empty(monkeypatch):
    monkeypatch.setattr(client_mod, "INCIDENT_BACKOFF", (0.01,))
    c = _client()
    sent: list[str] = []

    async def ok_post(payload):
        sent.append(payload["uuid"])
        return {"incident_id": 1, "snapshot_put_url": None, "duplicate": False}

    monkeypatch.setattr(c, "_post_incident", ok_post)
    c.queue_incident({"uuid": "only"}, None)
    for _ in range(200):
        if c.outbox_depth() == 0:
            break
        await asyncio.sleep(0.01)

    assert sent == ["only"]
    await c.stop_outbox()
    assert c._outbox_task is None
