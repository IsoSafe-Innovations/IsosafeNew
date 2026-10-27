"""Agent-side runtime tasks: live-stream uplink and periodic heartbeat.

Only started when AGENT_MODE=1. Both tasks are best-effort: a cloud outage must
never take down local detection, so every failure is logged and retried by the
underlying client (the stream reconnects itself with backoff; the heartbeat
loop simply retries on the next tick).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.agent.client import get_agent_client
from app.config import get_settings

log = logging.getLogger(__name__)


def build_heartbeat(streams: dict, uptime_s: float) -> dict[str, Any]:
    """Assemble the PRD v2 Phase 1a §5 heartbeat payload."""
    settings = get_settings()
    cpu = mem = disk_free_gb = None
    try:
        import psutil

        proc = psutil.Process()
        cpu = proc.cpu_percent(interval=None)
        mem = proc.memory_percent()
        disk_free_gb = round(psutil.disk_usage("/").free / (1024 ** 3), 1)
    except Exception:
        log.debug("process metrics unavailable", exc_info=True)

    cameras = []
    for cid, stream in streams.items():
        health = getattr(stream, "health", None)
        cameras.append(
            {
                "camera_id": cid,
                "online": not getattr(stream, "stopped", False),
                "fps": round(float(health.fps), 2) if health else 0.0,
                "reconnects": int(health.reconnect_count) if health else 0,
                "dropped": int(health.frames_dropped) if health else 0,
            }
        )

    payload: dict[str, Any] = {
        "agent_version": settings.agent_version,
        "uptime_s": round(uptime_s, 1),
        "cameras": cameras,
    }
    if cpu is not None:
        payload["cpu"] = round(cpu, 1)
        payload["mem"] = round(mem, 1)
        payload["disk_free_gb"] = disk_free_gb
    return payload


async def run_agent_heartbeat(streams: dict, stop_event: asyncio.Event) -> None:
    client = get_agent_client()
    interval = max(5, get_settings().agent_heartbeat_seconds)
    started = time.time()
    while not stop_event.is_set():
        try:
            await client.post_heartbeat(build_heartbeat(streams, time.time() - started))
        except Exception:
            log.exception("agent heartbeat failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass


async def run_agent_stream(stop_event: asyncio.Event) -> None:
    client = get_agent_client()
    await client.start_stream()
    try:
        await stop_event.wait()
    finally:
        await client.stop_outbox()
        await client.stop_stream()
