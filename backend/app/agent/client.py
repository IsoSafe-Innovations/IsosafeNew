"""Agent HTTP/WebSocket client for sending data to cloud in AGENT_MODE=1."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from contextlib import suppress
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

# Reconnect backoff for the live stream socket (seconds), capped at 30.
STREAM_BACKOFF = (1, 2, 4, 8, 16, 30)
# Retry backoff for the incident outbox after a cloud outage, capped at 30.
INCIDENT_BACKOFF = (1, 2, 4, 8, 16, 30)
PING = "ping"
PONG = "pong"


class AgentClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None
        # Separate client for presigned S3 PUTs: the bearer token must never be
        # sent to object storage (it is a different trust domain).
        self._upload_client: httpx.AsyncClient | None = None
        # Long-lived live-stream socket to the cloud.
        self._ws_task: asyncio.Task | None = None
        self._ws_queue: asyncio.Queue[str] | None = None
        self._ws_stop: asyncio.Event | None = None
        self._ws_connected = asyncio.Event()

        # Bounded incident outbox. When the cloud API is unreachable the agent
        # keeps incidents (and their JPEG) here and replays them on recovery.
        # Oldest are shed first once the cap is reached; the cloud upserts by
        # agent UUID, so a replay after a partial success never duplicates.
        self._outbox: deque[tuple[dict[str, Any], bytes | None]] = deque(
            maxlen=max(1, self.settings.agent_incident_queue_max)
        )
        self._outbox_task: asyncio.Task | None = None
        self._outbox_stop: asyncio.Event | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            base = self.settings.cloud_url.rstrip("/") if self.settings.cloud_url else "http://localhost:8000"
            headers = {}
            if self.settings.agent_token:
                headers["Authorization"] = f"Bearer {self.settings.agent_token}"
            self._client = httpx.AsyncClient(base_url=base, headers=headers, timeout=10.0)
        return self._client

    async def get_config(self) -> dict[str, Any]:
        """GET /agent/v1/config: pull the camera/zone/rule set from the cloud."""
        c = await self._ensure_client()
        r = await c.get("/agent/v1/config")
        r.raise_for_status()
        return r.json()

    async def post_heartbeat(self, payload: dict[str, Any] | None = None) -> None:
        try:
            c = await self._ensure_client()
            await c.post("/agent/v1/heartbeat", json=payload or {})
        except Exception:
            log.debug("agent heartbeat failed", exc_info=True)

    async def _post_incident(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /agent/v1/incidents, raising on failure; returns the cloud reply."""
        c = await self._ensure_client()
        r = await c.post("/agent/v1/incidents", json=payload)
        r.raise_for_status()
        return r.json()

    async def post_incident(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Best-effort POST /agent/v1/incidents; returns {} on failure."""
        try:
            return await self._post_incident(payload)
        except Exception:
            log.exception("agent incident post failed")
            return {}

    def outbox_depth(self) -> int:
        return len(self._outbox)

    def queue_incident(self, payload: dict[str, Any], jpeg: bytes | None = None) -> None:
        """Buffer an incident for delivery, retried across cloud outages.

        Bounded at ``agent_incident_queue_max``: when full the oldest incident is
        shed so a long outage can never grow agent memory without bound.
        """
        if self._outbox_stop is None:
            self._outbox_stop = asyncio.Event()
        self._outbox.append((payload, jpeg))
        if self._outbox_task is None or self._outbox_task.done():
            self._outbox_task = asyncio.create_task(self._outbox_loop(), name="agent-outbox")

    async def _outbox_loop(self) -> None:
        """Replay queued incidents in order; back off while the cloud is down."""
        idx = 0
        while self._outbox_stop is None or not self._outbox_stop.is_set():
            if not self._outbox:
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._outbox_stop.wait(), timeout=1.0)
                continue
            payload, jpeg = self._outbox[0]
            try:
                resp = await self._post_incident(payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = INCIDENT_BACKOFF[min(idx, len(INCIDENT_BACKOFF) - 1)]
                idx += 1
                log.info("agent incident outbox retry in %ss (depth=%d)", delay, len(self._outbox))
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._outbox_stop.wait(), timeout=delay)
                continue
            idx = 0
            put_url = resp.get("snapshot_put_url") if isinstance(resp, dict) else None
            if put_url and jpeg is not None:
                await self.put_snapshot(put_url, jpeg)
            self._outbox.popleft()

    async def stop_outbox(self) -> None:
        if self._outbox_stop is not None:
            self._outbox_stop.set()
        if self._outbox_task is not None:
            self._outbox_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._outbox_task
            self._outbox_task = None

    async def put_snapshot(self, url: str, jpeg: bytes) -> bool:
        """Upload JPEG bytes directly to the presigned S3 URL."""
        if self._upload_client is None:
            self._upload_client = httpx.AsyncClient(timeout=30.0)
        try:
            r = await self._upload_client.put(
                url, content=jpeg, headers={"Content-Type": "image/jpeg"}
            )
            r.raise_for_status()
            return True
        except Exception:
            log.exception("snapshot upload failed")
            return False

    @property
    def stream_connected(self) -> bool:
        return self._ws_connected.is_set()

    def _stream_url(self) -> str:
        base = self.settings.cloud_url or "http://localhost:8000"
        if base.startswith("https://"):
            ws = "wss://" + base[len("https://"):]
        elif base.startswith("http://"):
            ws = "ws://" + base[len("http://"):]
        elif base.startswith(("ws://", "wss://")):
            ws = base
        else:
            ws = "ws://" + base
        ws = ws.rstrip("/") + "/agent/v1/stream"
        if self.settings.agent_token:
            ws += "?token=" + quote(self.settings.agent_token, safe="")
        return ws

    async def start_stream(self) -> None:
        """Start the background live-stream socket (idempotent)."""
        if self._ws_task is not None:
            return
        self._ws_queue = asyncio.Queue(maxsize=32)
        self._ws_stop = asyncio.Event()
        self._ws_task = asyncio.create_task(self._stream_loop(), name="agent-ws")

    async def stop_stream(self) -> None:
        self._ws_connected.clear()
        if self._ws_stop is not None:
            self._ws_stop.set()
        if self._ws_task is not None:
            self._ws_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._ws_task
            self._ws_task = None
        self._ws_queue = None

    async def send_frame(self, frame_data: dict[str, Any]) -> None:
        """Queue a frame for the live stream; never blocks the pipeline."""
        if self._ws_queue is None:
            return
        try:
            data = json.dumps(frame_data, separators=(",", ":"))
        except (TypeError, ValueError):
            return
        if len(data.encode("utf-8", "ignore")) > self.settings.agent_max_message_bytes:
            log.debug("dropping oversized frame before send")
            return
        try:
            self._ws_queue.put_nowait(data)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self._ws_queue.get_nowait()
            with suppress(asyncio.QueueFull):
                self._ws_queue.put_nowait(data)

    async def _stream_loop(self) -> None:
        try:
            import websockets
        except ImportError:  # pragma: no cover - dependency is pinned
            log.error("websockets package missing; live stream disabled")
            return

        idx = 0
        while not (self._ws_stop is not None and self._ws_stop.is_set()):
            try:
                async with websockets.connect(
                    self._stream_url(),
                    ping_interval=None,
                    max_size=self.settings.agent_max_message_bytes * 2,
                    open_timeout=10,
                ) as ws:
                    idx = 0
                    self._ws_connected.set()
                    log.info("agent live stream connected")
                    await self._pump(ws)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.debug("agent live stream error", exc_info=True)
            finally:
                self._ws_connected.clear()

            if self._ws_stop is None or self._ws_stop.is_set():
                return
            delay = STREAM_BACKOFF[min(idx, len(STREAM_BACKOFF) - 1)]
            idx += 1
            log.info("agent live stream reconnecting in %ss", delay)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._ws_stop.wait(), timeout=delay)

    async def _pump(self, ws: Any) -> None:
        stop = asyncio.Event()
        tasks = [
            asyncio.create_task(self._ws_sender(ws, stop)),
            asyncio.create_task(self._ws_pinger(ws, stop)),
            asyncio.create_task(self._ws_receiver(ws, stop)),
        ]
        try:
            await stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _ws_sender(self, ws: Any, stop: asyncio.Event) -> None:
        assert self._ws_queue is not None
        try:
            while True:
                data = await self._ws_queue.get()
                await ws.send(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            stop.set()

    async def _ws_pinger(self, ws: Any, stop: asyncio.Event) -> None:
        interval = max(5, self.settings.agent_ws_ping_seconds)
        try:
            while True:
                await asyncio.sleep(interval)
                await ws.send(json.dumps({"type": PING}))
        except asyncio.CancelledError:
            raise
        except Exception:
            stop.set()

    async def _ws_receiver(self, ws: Any, stop: asyncio.Event) -> None:
        try:
            async for message in ws:
                if not isinstance(message, str):
                    continue
                try:
                    msg = json.loads(message)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(msg, dict) and msg.get("type") == PING:
                    await ws.send(json.dumps({"type": PONG}))
        except asyncio.CancelledError:
            raise
        except Exception:
            stop.set()

    async def close(self) -> None:
        await self.stop_outbox()
        await self.stop_stream()
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._upload_client is not None:
            await self._upload_client.aclose()
            self._upload_client = None


_agent_client: AgentClient | None = None


def get_agent_client() -> AgentClient:
    global _agent_client
    if _agent_client is None:
        _agent_client = AgentClient()
    return _agent_client
