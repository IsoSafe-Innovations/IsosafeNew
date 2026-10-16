"""DEMO-FR-26: the agent_offline incident is created once when the heartbeat is
stale and resolved on reconnect. These test the watchdog decision logic
(``_tick``) without a database by stubbing the DB side effects."""
import pytest

from app.agent import watchdog


@pytest.fixture
def spy(monkeypatch):
    calls = {"open": 0, "resolve": 0}

    async def fake_open():
        calls["open"] += 1
        return True

    async def fake_resolve():
        calls["resolve"] += 1
        return 1

    monkeypatch.setattr(watchdog, "open_offline_incident", fake_open)
    monkeypatch.setattr(watchdog, "resolve_offline_incidents", fake_resolve)
    return calls


def _health(age):
    async def fake():
        return {"online": age is not None and age <= 90, "last_seen_ago": age}

    return fake


@pytest.mark.asyncio
async def test_stale_heartbeat_opens_incident(monkeypatch, spy):
    monkeypatch.setattr(watchdog, "read_agent_health", _health(120))
    await watchdog._tick()
    assert spy == {"open": 1, "resolve": 0}


@pytest.mark.asyncio
async def test_fresh_heartbeat_resolves_incident(monkeypatch, spy):
    monkeypatch.setattr(watchdog, "read_agent_health", _health(10))
    await watchdog._tick()
    assert spy == {"open": 0, "resolve": 1}


@pytest.mark.asyncio
async def test_never_seen_agent_does_nothing(monkeypatch, spy):
    monkeypatch.setattr(watchdog, "read_agent_health", _health(None))
    await watchdog._tick()
    assert spy == {"open": 0, "resolve": 0}
