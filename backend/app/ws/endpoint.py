import asyncio
import contextlib
import json
import logging

import jwt as pyjwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.security import decode_token
from app.ws.manager import Client, manager

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query("")):
    try:
        payload = decode_token(token, expected_type="access")
    except pyjwt.PyJWTError:
        await ws.accept()
        await ws.close(code=4401, reason="Invalid token")
        return

    await ws.accept()
    client = Client(ws, email=payload["sub"], role=payload["role"])
    manager.register(client)

    async def sender():
        while True:
            message = await client.queue.get()
            await ws.send_text(message)

    send_task = asyncio.create_task(sender())
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            action = msg.get("action")
            ids = set(msg.get("camera_ids", []))
            if action == "subscribe":
                client.subscribed |= ids
            elif action == "unsubscribe":
                client.subscribed -= ids
            elif action == "set":
                client.subscribed = ids
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws receive error")
    finally:
        send_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await send_task
        manager.unregister(client)
