"""Resource guards: memory ceiling with worker recycle signal, disk space monitor
that pauses snapshot writes and fires a critical self-alert."""
import asyncio
import datetime as dt
import json
import logging
import shutil

import psutil

from app.alerts.incidents import set_snapshots_paused
from app.config import get_settings
from app.redis_client import ALERT_CHANNEL, get_redis

log = logging.getLogger(__name__)

CHECK_INTERVAL = 30.0


async def _fire_self_alert(description: str) -> None:
    payload = {
        "type": "incident",
        "camera_id": "system",
        "incident_type": "system_health",
        "severity": "critical",
        "description": description,
        "snapshot_url": None,
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    await get_redis().publish(ALERT_CHANNEL, json.dumps(payload))


async def run_resource_guards(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    proc = psutil.Process()
    disk_alerted = False
    while not stop_event.is_set():
        try:
            # Memory guard: log + restart signal (Docker restart policy recycles us)
            rss_mb = proc.memory_info().rss / (1024 * 1024)
            for child in proc.children(recursive=True):
                try:
                    rss_mb += child.memory_info().rss / (1024 * 1024)
                except psutil.NoSuchProcess:
                    pass
            if rss_mb > settings.worker_memory_limit_mb:
                log.critical(
                    "memory %dMB exceeds limit %dMB, exiting for recycle",
                    int(rss_mb), settings.worker_memory_limit_mb,
                )
                await _fire_self_alert(
                    f"Pipeline memory {int(rss_mb)}MB exceeded limit; recycling process"
                )
                raise SystemExit(3)

            # Disk guard
            usage = shutil.disk_usage(settings.media_root)
            free_gb = usage.free / (1024 ** 3)
            if free_gb < settings.disk_min_free_gb:
                if not disk_alerted:
                    disk_alerted = True
                    set_snapshots_paused(True)
                    log.critical("disk free %.1fGB below threshold, pausing snapshots", free_gb)
                    await _fire_self_alert(
                        f"Disk space low ({free_gb:.1f}GB free); snapshot writes paused"
                    )
            elif disk_alerted and free_gb > settings.disk_min_free_gb * 1.5:
                disk_alerted = False
                set_snapshots_paused(False)
                log.info("disk space recovered, resuming snapshots")
        except SystemExit:
            raise
        except Exception:
            log.exception("resource guard check failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CHECK_INTERVAL)
        except asyncio.TimeoutError:
            pass
