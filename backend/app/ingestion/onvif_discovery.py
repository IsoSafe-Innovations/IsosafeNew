"""ONVIF discovery: WS-Discovery scan of the local subnet, then pull stream URIs.

Returns candidate camera entries for admin approval; nothing is auto-added.
"""
import asyncio
import logging
import re
from urllib.parse import urlparse

log = logging.getLogger(__name__)


def _discover_sync(timeout: int = 5) -> list[dict]:
    from wsdiscovery.discovery import ThreadedWSDiscovery

    candidates: list[dict] = []
    wsd = ThreadedWSDiscovery()
    try:
        wsd.start()
        services = wsd.searchServices(timeout=timeout)
        for svc in services:
            xaddrs = svc.getXAddrs()
            types = " ".join(str(t) for t in svc.getTypes())
            if "onvif" not in types.lower() and not any("onvif" in x.lower() for x in xaddrs):
                continue
            for xaddr in xaddrs:
                parsed = urlparse(xaddr)
                if parsed.hostname:
                    candidates.append(
                        {
                            "host": parsed.hostname,
                            "port": parsed.port or 80,
                            "xaddr": xaddr,
                            "scopes": [str(s) for s in svc.getScopes()],
                        }
                    )
                    break
    finally:
        wsd.stop()
    return candidates


def _get_stream_uri_sync(host: str, port: int, username: str, password: str) -> str | None:
    try:
        from onvif import ONVIFCamera

        cam = ONVIFCamera(host, port, username, password)
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        if not profiles:
            return None
        req = media.create_type("GetStreamUri")
        req.ProfileToken = profiles[0].token
        req.StreamSetup = {
            "Stream": "RTP-Unicast",
            "Transport": {"Protocol": "RTSP"},
        }
        uri = media.GetStreamUri(req).Uri
        # Embed credentials for OpenCV if provided
        if username and uri.startswith("rtsp://") and "@" not in uri.split("://", 1)[1].split("/")[0]:
            uri = re.sub(r"^rtsp://", f"rtsp://{username}:{password}@", uri)
        return uri
    except Exception:
        log.exception("ONVIF stream URI fetch failed for %s:%s", host, port)
        return None


async def discover_cameras(timeout: int = 5) -> list[dict]:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _discover_sync, timeout)
    except Exception:
        log.exception("ONVIF discovery failed")
        return []


async def get_stream_uri(host: str, port: int, username: str = "", password: str = "") -> str | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_stream_uri_sync, host, port, username, password)
