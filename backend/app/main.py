"""FastAPI entrypoint (API process). The detection pipeline runs separately in
app.pipeline.runner; this process serves REST, WebSockets, and scheduled
insights, and bootstraps the first admin user."""
import asyncio
import contextlib
import logging
import os
import uuid

import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import (auth, cameras, detections, health, incidents, reports,
                     search, stats, uploads, users)
from app.config import get_settings
from app.db.engine import dispose, get_engine
from app.db.tables import users as users_table
from app.logging_config import request_id_var, setup_logging
from app.redis_client import close_redis
from app.search.insights import generate_insights
from app.security import hash_password
from app.ws import endpoint as ws_endpoint
from app.ws.manager import manager as ws_manager

log = logging.getLogger(__name__)

INSIGHTS_INTERVAL = 3600


async def _bootstrap_admin() -> None:
    """Create the first admin from env if the users table is empty."""
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@isosafe.local")
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    engine = get_engine()
    async with engine.begin() as conn:
        count = (
            await conn.execute(sa.select(sa.func.count()).select_from(users_table))
        ).scalar_one()
        if count > 0:
            return
        if not password:
            password = uuid.uuid4().hex[:12]
            log.warning("bootstrap admin created: %s / %s (change immediately)",
                        email, password)
        await conn.execute(
            sa.insert(users_table).values(
                id=uuid.uuid4(), email=email,
                password_hash=hash_password(password), role="admin",
            )
        )


async def _insights_loop(stop: asyncio.Event) -> None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=INSIGHTS_INTERVAL)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await generate_insights()
        except Exception:
            log.exception("scheduled insights generation failed")


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()
    app = FastAPI(title="Iso Safe", version="1.0.0",
                  description="AI video intelligence platform")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    for router in (auth.router, cameras.router, detections.router, incidents.router,
                   stats.router, uploads.router, search.router, reports.router,
                   health.router, users.router, ws_endpoint.router):
        app.include_router(router)

    # Snapshots/heatmaps served directly (nginx also serves these in production)
    if os.path.isdir(settings.media_root):
        app.mount("/media", StaticFiles(directory=settings.media_root), name="media")

    stop_event = asyncio.Event()
    background: list[asyncio.Task] = []

    @app.on_event("startup")
    async def startup() -> None:
        await _bootstrap_admin()
        await ws_manager.start()
        background.append(asyncio.create_task(_insights_loop(stop_event)))
        log.info("Iso Safe API started")

    @app.on_event("shutdown")
    async def shutdown() -> None:
        stop_event.set()
        await ws_manager.stop()
        for task in background:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await dispose()
        await close_redis()

    return app


app = create_app()
