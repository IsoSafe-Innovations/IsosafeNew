import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.ingestion.youtube import canonical_url, resolve_live, video_id
from app.ingestion.streams import CameraStream
from app.ingestion.health import CameraHealth

VIDEO = "Q71sLS8h9a4"
URL = f"https://www.youtube.com/watch?v={VIDEO}"


def test_encrypted_camera_serializes_public_player_id(monkeypatch):
    from cryptography.fernet import Fernet
    from app.config import get_settings
    from app.security import encrypt_source
    from app.api.cameras import _serialize

    monkeypatch.setenv("CAMERA_SECRET_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    try:
        result = _serialize({"id": "test", "type": "youtube", "source": encrypt_source(URL), "created_at": None})
        assert result["youtube_id"] == VIDEO
        assert result["source"] == URL
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("url", [URL, f"https://youtu.be/{VIDEO}?si=share",
    f"https://youtube.com/live/{VIDEO}", f"https://m.youtube.com/watch?v={VIDEO}&list=ignored"])
def test_canonical_video_links(url):
    assert video_id(url) == VIDEO
    assert canonical_url(url) == URL


@pytest.mark.parametrize("url", ["http://youtube.com/watch?v=" + VIDEO,
    "https://youtube.com.evil.test/watch?v=" + VIDEO, "https://localhost/",
    "https://youtube.com/playlist?list=test", "https://youtube.com/watch?v=invalid",
    "https://user:pass@youtube.com/watch?v=" + VIDEO])
def test_rejects_invalid_links(url):
    with pytest.raises(ValueError):
        canonical_url(url)


def test_resolver_selects_live_without_downloading(monkeypatch):
    import yt_dlp
    captured = {}

    class Extractor:
        def __init__(self, options):
            captured.update(options)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            assert url == URL and download is False
            return {"is_live": True, "url": "https://example.com/live.m3u8"}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Extractor)
    assert resolve_live(URL) == "https://example.com/live.m3u8"
    assert captured["live_from_start"] is False
    assert "720" in captured["format"]


async def test_disconnect_resolves_a_fresh_url(monkeypatch):
    from app.ingestion import streams

    stream = CameraStream("youtube-test", URL, "youtube")
    resolved = []
    monkeypatch.setattr(streams, "RECONNECT_BACKOFF", [0])
    monkeypatch.setattr(streams, "resolve_live", lambda _: f"https://example.com/{len(resolved)}")

    async def capture(source, realtime):
        resolved.append(source)
        assert realtime is True
        if len(resolved) == 2:
            stream.stop()
        return False

    monkeypatch.setattr(stream, "_run_capture", capture)
    await asyncio.wait_for(stream.run(), 2)
    assert resolved == ["https://example.com/0", "https://example.com/1"]


async def test_invalid_youtube_rejected_before_database():
    from app.api.cameras import CameraCreate, add_camera
    from app.api.deps import CurrentUser

    with pytest.raises(HTTPException) as exc:
        await add_camera(CameraCreate(name="Bad", type="youtube", source="https://localhost/"),
                         CurrentUser("admin@example.com", "admin"))
    assert exc.value.status_code == 422


async def test_reconnect_does_not_mark_failed_stream_online(monkeypatch):
    from app.ingestion import health
    import json

    saved = []
    async def store(key, value, **kwargs):
        saved.append(json.loads(value))
    monkeypatch.setattr(health, "get_redis", lambda: SimpleNamespace(set=store))
    camera = CameraHealth("test")
    camera.error = "connection failed"
    await camera.record_reconnect()
    assert saved[-1]["last_frame_ts"] == 0
    assert saved[-1]["error"] == "connection failed"
    await camera.record_frame()
    await camera._flush(1)
    assert saved[-1]["last_frame_ts"] > 0 and saved[-1]["error"] is None
