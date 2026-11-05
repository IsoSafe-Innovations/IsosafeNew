"""Persist website uploads as looping file cameras on the shared media volume."""
import os
import shutil
import uuid
from pathlib import Path

import cv2
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, require_operator, write_audit
from app.config import get_settings
from app.db.engine import get_engine
from app.db.tables import cameras, upload_jobs

router = APIRouter(prefix="/api/uploads", tags=["uploads"])
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
CHUNK = 1024 * 1024


def _save_video(file, dest: Path, max_bytes: int, reserve_bytes: int) -> None:
    """Bound disk use and verify a decodable frame, off the API event loop."""
    written = 0
    with dest.open("wb") as out:
        while chunk := file.read(CHUNK):
            written += len(chunk)
            if written > max_bytes:
                raise HTTPException(status_code=413, detail="Video exceeds the upload size limit")
            if shutil.disk_usage(dest.parent).free < reserve_bytes + len(chunk):
                raise HTTPException(status_code=507, detail="Not enough storage for this video")
            out.write(chunk)
    if written == 0:
        raise HTTPException(status_code=422, detail="The video file is empty")
    cap = cv2.VideoCapture(str(dest))
    try:
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        if not ok or frame is None:
            raise HTTPException(
                status_code=422,
                detail="This file cannot be read as a video. Try an MP4 encoded with H.264.",
            )
    finally:
        cap.release()


@router.get("/config")
async def upload_config(user: CurrentUser = Depends(require_operator)) -> dict:
    return {"max_mb": get_settings().upload_max_mb, "extensions": sorted(ALLOWED_EXTENSIONS)}


@router.post("", status_code=202)
async def create_upload(
    file: UploadFile,
    name: str = Form(default="", max_length=120),
    user: CurrentUser = Depends(require_operator),
) -> dict:
    settings = get_settings()
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail="Choose an MP4, MOV, AVI, MKV or WebM video")
    max_bytes = settings.upload_max_mb * CHUNK
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(status_code=413, detail=f"Video exceeds the {settings.upload_max_mb} MB limit")

    job_id = uuid.uuid4()
    camera_id = f"upload-{job_id.hex}"
    directory = Path(settings.media_root) / "uploads"
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"{job_id}{ext}"
    registered = False
    try:
        await run_in_threadpool(
            _save_video, file.file, dest, max_bytes,
            int(settings.disk_min_free_gb * 1024 ** 3),
        )
        engine = get_engine()
        async with engine.begin() as conn:
            # Serialize camera creation so concurrent uploads cannot exceed capacity.
            await conn.execute(sa.text("LOCK TABLE cameras IN SHARE ROW EXCLUSIVE MODE"))
            count = (await conn.execute(sa.select(sa.func.count()).select_from(cameras))).scalar_one()
            if count >= settings.max_cameras_per_node:
                raise HTTPException(status_code=409, detail="Camera limit reached. Remove a camera before uploading.")
            await conn.execute(sa.insert(cameras).values(
                id=camera_id, name=name.strip() or Path(filename).stem[:120],
                source=str(dest), type="file", loop_file=True,
                zones=[], rules=[], enabled=True,
            ))
            await conn.execute(sa.insert(upload_jobs).values(
                id=job_id, filename=filename, camera_id=camera_id,
                status="ready", completed_at=sa.func.now(),
            ))
        registered = True
    finally:
        if not registered:
            dest.unlink(missing_ok=True)

    await write_audit(user.email, "upload.create", str(job_id), {"filename": filename})
    return {"job_id": str(job_id), "camera_id": camera_id, "status": "ready"}


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
