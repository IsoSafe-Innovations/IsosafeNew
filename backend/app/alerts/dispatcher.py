"""Alert dispatcher: subscribes to the Redis alert channel and fans out to
email (SMTP, severity-gated) and webhooks (HMAC-signed POST).

WebSocket fanout happens in the API process (app.ws.manager), which subscribes
to the same channel.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.config import get_settings
from app.redis_client import ALERT_CHANNEL, get_redis

log = logging.getLogger(__name__)

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def _send_email_sync(subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s.smtp_from
    msg["To"] = s.alert_email_to
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
        server.starttls()
        if s.smtp_user:
            server.login(s.smtp_user, s.smtp_password)
        server.send_message(msg)


async def _dispatch_email(alert: dict) -> None:
    s = get_settings()
    if not s.smtp_host or not s.alert_email_to:
        return
    min_rank = SEVERITY_RANK.get(s.alert_email_min_severity, 2)
    if SEVERITY_RANK.get(alert.get("severity", "info"), 0) < min_rank:
        return
    subject = f"[Iso Safe {alert['severity'].upper()}] {alert['incident_type']} on {alert['camera_id']}"
    body = f"{alert['description']}\n\nTime: {alert['ts']}\nCamera: {alert['camera_id']}"
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _send_email_sync, subject, body)
    except Exception:
        log.exception("email dispatch failed")


async def _dispatch_webhook(alert: dict, client: httpx.AsyncClient) -> None:
    s = get_settings()
    if not s.webhook_url:
        return
    body = json.dumps(alert).encode()
    headers = {"Content-Type": "application/json"}
    if s.webhook_secret:
        sig = hmac.new(s.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-IsoSafe-Signature"] = f"sha256={sig}"
    try:
        resp = await client.post(s.webhook_url, content=body, headers=headers, timeout=10)
        if resp.status_code >= 400:
            log.warning("webhook returned %s", resp.status_code)
    except Exception:
        log.exception("webhook dispatch failed")


async def run_dispatcher(stop_event: asyncio.Event | None = None) -> None:
    """Long-running task; resilient to Redis hiccups."""
    stop_event = stop_event or asyncio.Event()
    async with httpx.AsyncClient() as client:
        while not stop_event.is_set():
            try:
                pubsub = get_redis().pubsub()
                await pubsub.subscribe(ALERT_CHANNEL)
                async for message in pubsub.listen():
                    if stop_event.is_set():
                        break
                    if message["type"] != "message":
                        continue
                    try:
                        alert = json.loads(message["data"])
                    except (json.JSONDecodeError, TypeError):
                        continue
                    await asyncio.gather(
                        _dispatch_email(alert),
                        _dispatch_webhook(alert, client),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("alert dispatcher error, restarting in 3s")
                await asyncio.sleep(3)
