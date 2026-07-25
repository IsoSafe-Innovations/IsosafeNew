"""WebSocket manager backed by Redis pub/sub so multiple Gunicorn workers share fanout.

Message types sent to clients:
  {"type": "frame", "camera_id", "image", "counts", "in_frame", "ts"}
  {"type": "incident", "camera_id", "incident_type", "severity", "description",
   "snapshot_url", "ts"}
  {"type": "counts", "camera_id", "counts", "in_frame", "ts"}   (unsubscribed cameras)

Clients send:
  {"action": "subscribe", "camera_ids": ["cam-1", ...]}
  {"action": "unsubscribe", "camera_ids": [...]}

Frame throttling: full frames only for cameras a client subscribed to; every
other camera delivers lightweight count updates. Bandwidth stays linear with
what the operator is actually watching.
"""
import asyncio
import contextlib
import json
import logging

from fastapi import WebSocket

from app.metrics import WS_CLIENTS
from app.redis_client import ALERT_CHANNEL, FRAME_CHANNEL, get_redis

log = logging.getLogger(__name__)

MAX_SEND_QUEUE = 30


class Client:
    def __init__(self, ws: WebSocket, email: str, role: str):
        self.ws = ws
        self.email = email
        self.role = role
        self.subscribed: set[str] = set()
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_SEND_QUEUE)

    def enqueue(self, message: str) -> None:
        """Drop-oldest so one slow client never grows backend memory."""
        while True:
            try:
                self.queue.put_nowait(message)
                return
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    self.queue.get_nowait()


class WSManager:
    def __init__(self) -> None:
        self.clients: set[Client] = set()
        self._pump_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._pump_task is None:
            self._pump_task = asyncio.create_task(self._redis_pump())

    async def stop(self) -> None:
        if self._pump_task:
            self._pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pump_task
            self._pump_task = None

    def register(self, client: Client) -> None:
        self.clients.add(client)
        WS_CLIENTS.set(len(self.clients))

    def unregister(self, client: Client) -> None:
        self.clients.discard(client)
        WS_CLIENTS.set(len(self.clients))

    async def _redis_pump(self) -> None:
        """Single Redis subscription per API worker; fan out locally."""
        while True:
            try:
                pubsub = get_redis().pubsub()
                await pubsub.subscribe(FRAME_CHANNEL, ALERT_CHANNEL)
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    self._route(message["channel"], message["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ws redis pump error, retrying in 2s")
                await asyncio.sleep(2)

    def _route(self, channel: str, data: str) -> None:
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return

        if channel == ALERT_CHANNEL:
            # incidents go to everyone
            for client in self.clients:
                client.enqueue(data)
            return

        camera_id = payload.get("camera_id")
        # Full frames to subscribers; counts-only to the rest
        counts_msg: str | None = None
        for client in self.clients:
            if camera_id in client.subscribed:
                client.enqueue(data)
            else:
                if counts_msg is None:
                    counts_msg = json.dumps({
                        "type": "counts",
                        "camera_id": camera_id,
                        "counts": payload.get("counts", {}),
                        "in_frame": payload.get("in_frame", {}),
                        "ts": payload.get("ts"),
                    })
                client.enqueue(counts_msg)


manager = WSManager()
