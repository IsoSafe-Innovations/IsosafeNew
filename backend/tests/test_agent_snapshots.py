"""Snapshot delivery contract: 5-minute presigned S3 GET, never /media on staging.

The PRD expiry test (open now -> 200, open after 5 min -> 403) is enforced by the
signature's ``X-Amz-Expires`` window; we assert that window is 300s, which is the
part the application controls. ``test_presigned_get_expires_live`` runs the real
MinIO/S3 clock check (with a short presign) when an endpoint is configured.
"""
import datetime as dt
import os
import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import get_settings


def test_presign_windows_default_to_five_minutes():
    get_settings.cache_clear()
    s = get_settings()
    assert s.s3_presign_get_seconds == 300
    assert s.s3_presign_put_seconds == 300


def test_presigned_get_url_expires_in_300s(monkeypatch):
    pytest.importorskip("boto3")
    monkeypatch.setenv("S3_BUCKET", "isosafe-snapshots")
    monkeypatch.setenv("S3_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("S3_SECRET_KEY", "minioadmin")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setenv("S3_PUBLIC_ENDPOINT_URL", "http://localhost:9000")
    get_settings.cache_clear()
    try:
        from app.storage import presigned_get_url

        url = presigned_get_url("snapshots/2026/10/09/x.jpg")
        qs = parse_qs(urlparse(url).query)
        assert qs["X-Amz-Expires"] == ["300"]
        assert "X-Amz-Signature" in qs
    finally:
        get_settings.cache_clear()


def test_snapshot_url_uses_presigned_s3_in_agent_mode(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "1")
    monkeypatch.setenv("S3_BUCKET", "isosafe-snapshots")
    get_settings.cache_clear()
    try:
        from app import storage

        monkeypatch.setattr(storage, "presigned_get_url", lambda key: "https://signed/get.jpg")
        assert storage.snapshot_url("snapshots/2026/10/09/x.jpg") == "https://signed/get.jpg"
    finally:
        get_settings.cache_clear()


def test_snapshot_url_never_falls_back_to_media_in_agent_mode(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "1")
    get_settings.cache_clear()
    try:
        from app import storage

        monkeypatch.setattr(storage, "presigned_get_url", lambda key: None)
        # No signing -> no URL. The old public /media route is not exposed on staging.
        assert storage.snapshot_url("snapshots/2026/10/09/x.jpg") is None
    finally:
        get_settings.cache_clear()


def test_incident_response_returns_presigned_snapshot_not_media(monkeypatch):
    """DEMO-FR-23: list/detail incident payloads carry a presigned S3 GET."""
    monkeypatch.setenv("AGENT_MODE", "1")
    monkeypatch.setenv("S3_BUCKET", "isosafe-snapshots")
    get_settings.cache_clear()
    try:
        from app import storage

        monkeypatch.setattr(
            storage,
            "presigned_get_url",
            lambda key: "https://signed/get.jpg?X-Amz-Expires=300&X-Amz-Signature=abc",
        )
        from app.api.incidents import _serialize

        row = {
            "id": 1,
            "uuid": "12345678-1234-5678-1234-567812345678",
            "camera_id": "cam-1",
            "ts": dt.datetime(2026, 10, 9, tzinfo=dt.UTC),
            "incident_type": "loitering",
            "severity": "critical",
            "description": "Person loitering",
            "snapshot_path": "snapshots/2026/10/09/x.jpg",
            "status": "open",
            "resolved_at": None,
            "assigned_to": None,
            "resolution_notes": None,
        }
        out = _serialize(row)
        assert "X-Amz-Expires=300" in out["snapshot_url"]
        assert "/media/" not in out["snapshot_url"]
        assert "uuid" not in out
    finally:
        get_settings.cache_clear()


def test_presigned_get_expires_live():
    """Open now -> 200, open after the window -> 403, against a live S3/MinIO.

    Skipped unless S3_BUCKET and S3_ENDPOINT_URL are set to a reachable server.
    Uses a 1 s presign so the clock check is fast; the app default stays 300 s.
    """
    pytest.importorskip("boto3")
    bucket = os.environ.get("S3_BUCKET")
    endpoint = os.environ.get("S3_ENDPOINT_URL")
    if not (bucket and endpoint):
        pytest.skip("set S3_BUCKET and S3_ENDPOINT_URL to run the live expiry test")

    import boto3
    from botocore.config import Config

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY") or None,
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY") or None,
        config=Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=5,
            retries={"max_attempts": 1},
        ),
    )
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"S3 endpoint {endpoint} not reachable: {e!r}")

    key = f"snapshots/{dt.datetime.now(dt.UTC):%Y/%m/%d}/{uuid.uuid4()}.jpg"
    s3.put_object(Bucket=bucket, Key=key, Body=b"\xff\xd8\xff\xd9", ContentType="image/jpeg")

    get_settings.cache_clear()
    try:
        from app.storage import presigned_get_url

        url = presigned_get_url(key, expires=4)
    finally:
        get_settings.cache_clear()

    assert url and "X-Amz-Expires=4" in url
    assert httpx.get(url, timeout=10).status_code == 200
    time.sleep(6)
    assert httpx.get(url, timeout=10).status_code == 403
