"""Private object storage for incident snapshots (S3 in cloud, MinIO locally).

The cloud never proxies JPEG bytes through the API server. It only mints
short-lived presigned URLs:

  * PUT  - handed to the agent so it can upload the annotated snapshot directly.
  * GET  - returned in incident payloads so the dashboard ``<img src>`` works.

S3 key layout is fixed by the PRD:
  snapshots/{yyyy}/{mm}/{dd}/{incident_uuid}.jpg
"""
from __future__ import annotations

import datetime as dt
import logging

from app.config import get_settings

log = logging.getLogger(__name__)

SNAPSHOT_PREFIX = "snapshots"
JPEG_CONTENT_TYPE = "image/jpeg"


def snapshot_key(incident_uuid: str, ts: dt.datetime | float) -> str:
    """Build the PRD-mandated S3 key for an incident snapshot."""
    if isinstance(ts, (int, float)):
        when = dt.datetime.fromtimestamp(ts, tz=dt.UTC)
    else:
        when = ts if ts.tzinfo else ts.replace(tzinfo=dt.UTC)
    return f"{SNAPSHOT_PREFIX}/{when:%Y/%m/%d}/{incident_uuid}.jpg"


def is_configured() -> bool:
    return bool(get_settings().s3_bucket)


def _client(*, public: bool):
    """Build a boto3 S3 client. ``public`` signs URLs for the externally
    reachable endpoint (e.g. a browser), while operations use the internal one."""
    import boto3
    from botocore.config import Config

    settings = get_settings()
    endpoint = settings.s3_endpoint_url
    if public:
        endpoint = settings.s3_public_endpoint_url or settings.s3_endpoint_url
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key or None,
        aws_secret_access_key=settings.s3_secret_key or None,
        config=Config(signature_version="s3v4"),
    )


def presigned_put_url(key: str, expires: int | None = None) -> str | None:
    """5-minute presigned PUT for ``key``, or None when storage is unconfigured."""
    settings = get_settings()
    if not key or not settings.s3_bucket:
        return None
    try:
        return _client(public=True).generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.s3_bucket,
                "Key": key,
                "ContentType": JPEG_CONTENT_TYPE,
            },
            ExpiresIn=expires or settings.s3_presign_put_seconds,
        )
    except Exception:
        log.exception("presigned PUT generation failed")
        return None


def presigned_get_url(key: str, expires: int | None = None) -> str | None:
    """5-minute presigned GET for ``key``, or None when storage is unconfigured."""
    settings = get_settings()
    if not key or not settings.s3_bucket:
        return None
    try:
        return _client(public=True).generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": key},
            ExpiresIn=expires or settings.s3_presign_get_seconds,
        )
    except Exception:
        log.exception("presigned GET generation failed")
        return None


def snapshot_url(path: str | None) -> str | None:
    """Resolve a stored ``snapshot_path`` to a browser-usable URL.

    Cloud (agent) mode returns a presigned S3 GET and never the public ``/media``
    route (it 404s on staging). Local v1 mode keeps the nginx/API ``/media`` path.
    """
    if not path:
        return None
    settings = get_settings()
    if settings.agent_mode:
        return presigned_get_url(path)
    return f"/media/{path}"
