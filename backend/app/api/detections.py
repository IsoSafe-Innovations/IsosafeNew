"""Detection queries with cursor pagination (never OFFSET at this table size)."""
import base64
import datetime as dt
import json

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import CurrentUser, require_viewer
from app.db.engine import get_engine
from app.db.tables import detections

router = APIRouter(prefix="/api/detections", tags=["detections"])


def _encode_cursor(ts: dt.datetime, row_id: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"ts": ts.isoformat(), "id": row_id}).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[dt.datetime, int]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return dt.datetime.fromisoformat(data["ts"]), int(data["id"])
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid cursor")


@router.get("")
async def list_detections(
    camera: str | None = None,
    from_ts: dt.datetime | None = Query(None, alias="from"),
    to_ts: dt.datetime | None = Query(None, alias="to"),
    type: str | None = None,
    plate: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    cursor: str | None = None,
    user: CurrentUser = Depends(require_viewer),
) -> dict:
    query = sa.select(detections)
    if camera:
        query = query.where(detections.c.camera_id == camera)
    if from_ts:
        query = query.where(detections.c.ts >= from_ts)
    if to_ts:
        query = query.where(detections.c.ts <= to_ts)
    if type:
        query = query.where(detections.c.object_type == type)
    if plate:
        query = query.where(detections.c.plate_text.ilike(f"%{plate.upper()}%"))
    if cursor:
        cur_ts, cur_id = _decode_cursor(cursor)
        query = query.where(
            sa.or_(
                detections.c.ts < cur_ts,
                sa.and_(detections.c.ts == cur_ts, detections.c.id < cur_id),
            )
        )
    query = query.order_by(detections.c.ts.desc(), detections.c.id.desc()).limit(limit + 1)

    engine = get_engine()
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).mappings().all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {
            **dict(r),
            "ts": r["ts"].isoformat(),
            "bbox": list(r["bbox"]) if r["bbox"] else None,
            "zone_ids": list(r["zone_ids"]) if r["zone_ids"] else [],
        }
        for r in rows
    ]
    next_cursor = _encode_cursor(rows[-1]["ts"], rows[-1]["id"]) if has_more and rows else None
    return {"items": items, "next_cursor": next_cursor}
