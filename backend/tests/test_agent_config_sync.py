"""Agent mode pulls camera config from the cloud instead of a local DB.

This is the missing link that makes the midpoint demo work on the real topology
(site agent, cloud elsewhere): the agent's Pipeline.reconcile() must reconcile
against ``GET /agent/v1/config``.
"""
import asyncio

from app.agent.client import AgentClient
from app.config import get_settings


async def test_get_config_calls_cloud_endpoint(monkeypatch):
    c = AgentClient()
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"config_version": "v1", "cameras": [{"id": "cam-1"}]}

    class _FakeClient:
        async def get(self, path):
            captured["path"] = path
            return _Resp()

    async def _ensure():
        return _FakeClient()

    monkeypatch.setattr(c, "_ensure_client", _ensure)
    cfg = await c.get_config()
    assert captured["path"] == "/agent/v1/config"
    assert cfg["cameras"][0]["id"] == "cam-1"


async def test_agent_mode_reconcile_starts_cloud_cameras(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "1")
    get_settings.cache_clear()
    try:
        from app.pipeline import runner as runner_mod

        class _Agent:
            async def get_config(self):
                return {
                    "config_version": "v1",
                    "cameras": [
                        {
                            "id": "cam-1", "name": "Front", "source": "file:///demo.mp4",
                            "type": "file", "zones": [], "rules": [], "refresh_secs": 2.0,
                            "loop_file": True, "enabled": True,
                        }
                    ],
                }

        monkeypatch.setattr("app.agent.client.get_agent_client", lambda: _Agent())

        started = asyncio.Event()

        async def _idle_run(self):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(runner_mod.CameraStream, "run", _idle_run)

        pipe = runner_mod.Pipeline()
        await pipe.reconcile()
        await asyncio.wait_for(started.wait(), timeout=1)
        assert set(pipe.streams) == {"cam-1"}

        for task in pipe.stream_tasks.values():
            task.cancel()
        await asyncio.gather(*pipe.stream_tasks.values(), return_exceptions=True)
    finally:
        get_settings.cache_clear()


async def test_agent_mode_reconcile_keeps_cameras_when_cloud_down(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "1")
    get_settings.cache_clear()
    try:
        from app.pipeline import runner as runner_mod

        state = {"up": True}

        class _Agent:
            async def get_config(self):
                if not state["up"]:
                    raise RuntimeError("cloud down")
                return {"config_version": "v1", "cameras": [
                    {"id": "cam-1", "name": "Front", "source": "file:///demo.mp4",
                     "type": "file", "zones": [], "rules": [], "refresh_secs": 2.0,
                     "loop_file": True, "enabled": True}]}

        monkeypatch.setattr("app.agent.client.get_agent_client", lambda: _Agent())

        async def _idle_run(self):
            await asyncio.Event().wait()

        monkeypatch.setattr(runner_mod.CameraStream, "run", _idle_run)

        pipe = runner_mod.Pipeline()
        await pipe.reconcile()
        assert "cam-1" in pipe.streams

        state["up"] = False
        await pipe.reconcile()  # must not tear down the running camera
        assert "cam-1" in pipe.streams

        for task in pipe.stream_tasks.values():
            task.cancel()
        await asyncio.gather(*pipe.stream_tasks.values(), return_exceptions=True)
    finally:
        get_settings.cache_clear()
