"""Video upload processing: multipart with a 500MB cap, saved to the media volume,
then registered as a single-pass file camera the pipeline picks up."""
import logging
import os
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.api.deps import CurrentUser, require_operator, write_audit
from app.config import get_settings
from app.db.engine import get_engine
from app.db.tables import cameras, upload_jobs

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uploads", tags=["uploads"])

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
CHUNK = 1024 * 1024


@router.post("", status_code=202)
async def create_upload(
    file: UploadFile, user: CurrentUser = Depends(require_operator)
) -> dict:
    settings = get_settings()
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported file type {ext}")

    job_id = uuid.uuid4()
    directory = os.path.join(settings.media_root, "uploads")
    os.makedirs(directory, exist_ok=True)
    dest = os.path.join(directory, f"{job_id}{ext}")

    max_bytes = settings.upload_max_mb * 1024 * 1024
    written = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(CHUNK):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {settings.upload_max_mb}MB cap",
                    )
                out.write(chunk)
    except HTTPException:
        if os.path.exists(dest):
            os.remove(dest)
        raise

    camera_id = f"upload-{str(job_id)[:8]}"
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            sa.insert(upload_jobs).values(
                id=job_id, filename=file.filename, camera_id=camera_id, status="processing"
            )
        )
        # single-pass file camera; pipeline reconciler picks it up within 15s
        await conn.execute(
            sa.insert(cameras).values(
                id=camera_id,
                name=f"Upload: {file.filename}",
                source=dest,
                type="file",
                loop_file=False,
                zones=[],
                rules=[],
                enabled=True,
            )
        )
    await write_audit(user.email, "upload.create", str(job_id), {"filename": file.filename})
    return {"job_id": str(job_id), "camera_id": camera_id, "status": "processing"}


@router.get("/{job_id}")
async def get_upload(job_id: uuid.UUID, user: CurrentUser = Depends(require_operator)) -> dict:
    engine = get_engine()
    async with engine.connect() as conn:
        row = (
            await conn.execute(sa.select(upload_jobs).where(upload_jobs.c.id == job_id))
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Upload job not found")
    return {
        **dict(row),
        "id": str(row["id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
    }
