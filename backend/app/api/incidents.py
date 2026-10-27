import datetime as dt

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import CurrentUser, require_operator, require_viewer, write_audit
from app.db.engine import get_engine
from app.db.tables import incidents
from app.storage import snapshot_url

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

VALID_STATUSES = {"open", "investigating", "resolved", "closed"}
# permitted transitions
TRANSITIONS = {
    "open": {"investigating", "resolved", "closed"},
    "investigating": {"resolved", "closed", "open"},
    "resolved": {"closed", "open"},
    "closed": {"open"},
}


class IncidentPatch(BaseModel):
    status: str | None = None
    assigned_to: str | None = None
    resolution_notes: str | None = None


def _serialize(row: dict) -> dict:
    out = dict(row)
    out["ts"] = row["ts"].isoformat()
    out["resolved_at"] = row["resolved_at"].isoformat() if row["resolved_at"] else None
    out["snapshot_url"] = snapshot_url(row["snapshot_path"])
    out.pop("uuid", None)
    return out


@router.get("")
async def list_incidents(
    status: str | None = None,
    severity: str | None = None,
    camera: str | None = None,
    from_ts: dt.datetime | None = Query(None, alias="from"),
    to_ts: dt.datetime | None = Query(None, alias="to"),
    incident_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    user: CurrentUser = Depends(require_viewer),
) -> list[dict]:
    query = sa.select(incidents)
    if status:
        query = query.where(incidents.c.status == status)
    if severity:
        query = query.where(incidents.c.severity == severity)
    if camera:
        query = query.where(incidents.c.camera_id == camera)
    if incident_type:
        query = query.where(incidents.c.incident_type == incident_type)
    if from_ts:
        query = query.where(incidents.c.ts >= from_ts)
    if to_ts:
        query = query.where(incidents.c.ts <= to_ts)
    query = query.order_by(incidents.c.ts.desc()).limit(limit)

    engine = get_engine()
    async with engine.connect() as conn:
        rows = (await conn.execute(query)).mappings().all()
    return [_serialize(r) for r in rows]


@router.get("/{incident_id}")
async def get_incident(incident_id: int, user: CurrentUser = Depends(require_viewer)) -> dict:
    engine = get_engine()
    async with engine.connect() as conn:
        row = (
            await conn.execute(sa.select(incidents).where(incidents.c.id == incident_id))
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _serialize(row)


@router.patch("/{incident_id}")
async def patch_incident(
    incident_id: int, body: IncidentPatch, user: CurrentUser = Depends(require_operator)
) -> dict:
    engine = get_engine()
    async with engine.begin() as conn:
        row = (
            await conn.execute(sa.select(incidents).where(incidents.c.id == incident_id))
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Incident not found")

        updates: dict = {}
        if body.status is not None:
            if body.status not in VALID_STATUSES:
                raise HTTPException(status_code=422, detail="Invalid status")
            if body.status != row["status"] and body.status not in TRANSITIONS[row["status"]]:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot transition {row['status']} -> {body.status}",
                )
            updates["status"] = body.status
            if body.status == "resolved":
                updates["resolved_at"] = dt.datetime.now(dt.UTC)
        if body.assigned_to is not None:
            updates["assigned_to"] = body.assigned_to
        if body.resolution_notes is not None:
            updates["resolution_notes"] = body.resolution_notes
        if not updates:
            raise HTTPException(status_code=422, detail="No fields to update")

        await conn.execute(
            sa.update(incidents).where(incidents.c.id == incident_id).values(**updates)
        )
        row = (
            await conn.execute(sa.select(incidents).where(incidents.c.id == incident_id))
        ).mappings().one()
    await write_audit(user.email, "incident.update", str(incident_id), updates if "resolved_at" not in updates else {**updates, "resolved_at": updates["resolved_at"].isoformat()})
    return _serialize(row)
