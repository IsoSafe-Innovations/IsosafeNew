"""Report generation: PDF (reportlab) and Excel (openpyxl) from analytics + incidents."""
import datetime as dt
import io
import logging

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, require_viewer
from app.db.engine import get_engine
from app.db.tables import analytics_hourly, cameras, incidents

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["reports"])

REPORT_TYPES = {
    "daily_summary": "Daily Summary",
    "weekly_security": "Weekly Security",
    "monthly_business": "Monthly Business",
    "incident_report": "Incident Report",
    "camera_health": "Camera Health",
}


async def _gather(report_type: str, from_ts: dt.datetime, to_ts: dt.datetime) -> dict:
    engine = get_engine()
    async with engine.connect() as conn:
        cams = (await conn.execute(sa.select(cameras))).mappings().all()
        hourly = (
            await conn.execute(
                sa.select(analytics_hourly)
                .where(analytics_hourly.c.bucket >= from_ts,
                       analytics_hourly.c.bucket <= to_ts)
                .order_by(analytics_hourly.c.bucket)
            )
        ).mappings().all()
        incs = (
            await conn.execute(
                sa.select(incidents)
                .where(incidents.c.ts >= from_ts, incidents.c.ts <= to_ts)
                .order_by(incidents.c.ts.desc())
            )
        ).mappings().all()
    return {"cameras": cams, "hourly": hourly, "incidents": incs}


def _build_pdf(report_type: str, data: dict, from_ts, to_ts) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)
    from reportlab.lib.styles import getSampleStyleSheet

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=REPORT_TYPES[report_type])
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Iso Safe — {REPORT_TYPES[report_type]}", styles["Title"]),
        Paragraph(f"Period: {from_ts:%Y-%m-%d %H:%M} to {to_ts:%Y-%m-%d %H:%M} UTC",
                  styles["Normal"]),
        Spacer(1, 0.5 * cm),
    ]

    total_footfall = sum(r["footfall"] or 0 for r in data["hourly"])
    total_incidents = len(data["incidents"])
    critical = sum(1 for i in data["incidents"] if i["severity"] == "critical")
    story.append(Paragraph(
        f"Total footfall: {total_footfall} &nbsp;&nbsp; Incidents: {total_incidents} "
        f"({critical} critical) &nbsp;&nbsp; Cameras: {len(data['cameras'])}",
        styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    if report_type == "camera_health":
        rows = [["Camera", "Type", "Profile", "Enabled"]] + [
            [c["id"], c["type"], c["vertical_profile"] or "-", "yes" if c["enabled"] else "no"]
            for c in data["cameras"]
        ]
    elif report_type in ("weekly_security", "incident_report"):
        rows = [["Time (UTC)", "Camera", "Type", "Severity", "Status"]] + [
            [i["ts"].strftime("%m-%d %H:%M"), i["camera_id"], i["incident_type"],
             i["severity"], i["status"]]
            for i in data["incidents"][:200]
        ]
    else:
        per_cam: dict[str, int] = {}
        for r in data["hourly"]:
            per_cam[r["camera_id"]] = per_cam.get(r["camera_id"], 0) + (r["footfall"] or 0)
        rows = [["Camera", "Footfall", "Incidents"]] + [
            [cid, str(ff),
             str(sum(1 for i in data["incidents"] if i["camera_id"] == cid))]
            for cid, ff in sorted(per_cam.items(), key=lambda kv: -kv[1])
        ]

    if len(rows) > 1:
        table = Table(rows, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("No data in the selected period.", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()


def _build_xlsx(report_type: str, data: dict, from_ts, to_ts) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"Iso Safe — {REPORT_TYPES[report_type]}"])
    ws.append([f"Period: {from_ts:%Y-%m-%d} to {to_ts:%Y-%m-%d} (UTC)"])
    ws.append([])

    ws.append(["Camera", "Bucket (UTC)", "Footfall", "Avg queue", "Max queue",
               "Avg occupancy", "Incidents"])
    for r in data["hourly"]:
        ws.append([r["camera_id"], r["bucket"].strftime("%Y-%m-%d %H:%M"),
                   r["footfall"], r["avg_queue"], r["max_queue"],
                   r["avg_occupancy"], r["incident_count"]])

    ws2 = wb.create_sheet("Incidents")
    ws2.append(["Time (UTC)", "Camera", "Type", "Severity", "Status", "Description"])
    for i in data["incidents"]:
        ws2.append([i["ts"].strftime("%Y-%m-%d %H:%M"), i["camera_id"],
                    i["incident_type"], i["severity"], i["status"], i["description"]])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/{report_type}")
async def generate_report(
    report_type: str,
    from_ts: dt.datetime | None = Query(None, alias="from"),
    to_ts: dt.datetime | None = Query(None, alias="to"),
    format: str = Query("pdf", pattern="^(pdf|xlsx)$"),
    user: CurrentUser = Depends(require_viewer),
) -> StreamingResponse:
    if report_type not in REPORT_TYPES:
        raise HTTPException(status_code=404, detail=f"Unknown report type {report_type}")
    now = dt.datetime.now(dt.timezone.utc)
    defaults = {
        "daily_summary": 1, "weekly_security": 7, "monthly_business": 30,
        "incident_report": 7, "camera_health": 1,
    }
    to_ts = to_ts or now
    from_ts = from_ts or (to_ts - dt.timedelta(days=defaults[report_type]))

    data = await _gather(report_type, from_ts, to_ts)
    if format == "pdf":
        content = _build_pdf(report_type, data, from_ts, to_ts)
        media_type = "application/pdf"
        ext = "pdf"
    else:
        content = _build_xlsx(report_type, data, from_ts, to_ts)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = "xlsx"
    filename = f"isosafe_{report_type}_{to_ts:%Y%m%d}.{ext}"
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
