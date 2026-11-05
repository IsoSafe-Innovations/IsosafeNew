"""Canonical YouTube URLs and fresh, bounded-resolution live stream discovery."""
import re
from urllib.parse import parse_qs, urlsplit


def video_id(source: str) -> str:
    url = urlsplit(source.strip())
    if url.scheme != "https" or url.username or url.password or url.port not in (None, 443):
        raise ValueError("Use an HTTPS YouTube video link")
    host = (url.hostname or "").lower()
    if host == "youtu.be":
        candidate = url.path.strip("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        parts = url.path.strip("/").split("/")
        candidate = parse_qs(url.query).get("v", [""])[0] if url.path == "/watch" else (
            parts[1] if len(parts) == 2 and parts[0] in {"live", "embed"} else ""
        )
    else:
        raise ValueError("Use a youtube.com or youtu.be video link")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        raise ValueError("The YouTube link must identify one video")
    return candidate


def canonical_url(source: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id(source)}"


def resolve_live(source: str) -> str:
    from yt_dlp import YoutubeDL

    options = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "socket_timeout": 10, "retries": 1, "extractor_retries": 1,
        "live_from_start": False,
        "js_runtimes": {"node": {}},
        "format": "bestvideo[height<=720][protocol^=m3u8]/best[height<=720]/bestvideo[height<=720]",
    }
    with YoutubeDL(options) as extractor:
        info = extractor.extract_info(canonical_url(source), download=False)
    if not info or not info.get("is_live"):
        raise ValueError("This YouTube video is not currently live")
    stream = info.get("url")
    if not stream or urlsplit(stream).scheme != "https":
        raise ValueError("No playable HTTPS live stream was returned")
    return stream
