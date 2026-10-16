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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent.watchdog import run_agent_watchdog
from app.api import agent, auth, cameras, detections, health, incidents, reports, search, stats, uploads, users
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


class AgentBodyLimitMiddleware:
    """Cap ``/agent/*`` request bodies at 1 MB (PRD v2 DEMO-FR-27).

    A declared ``Content-Length`` is checked up front. Chunked uploads (no
    ``Content-Length``) are measured as they stream and rejected the moment they
    exceed the cap, so the body is never buffered past the limit. Requests under
    the cap are buffered and replayed unchanged to the route.
    """

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/agent/"):
            await self.app(scope, receive, send)
            return

        content_length = None
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                content_length = value
                break

        if content_length is not None:
            try:
                too_big = int(content_length) > self.max_bytes
            except ValueError:
                too_big = True
            if too_big:
                await self._reject(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        messages: list[dict] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                messages.append(message)
                break
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break

        index = 0

        async def replay():
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay, send)

    async def _reject(self, scope, receive, send) -> None:
        response = JSONResponse(status_code=413, content={"detail": "agent message exceeds 1 MB"})
        await response(scope, receive, send)


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
        except TimeoutError:
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

    # The cloud drops any agent message > 1 MB before it is parsed (DEMO-FR-22/27).
    app.add_middleware(AgentBodyLimitMiddleware, max_bytes=settings.agent_max_message_bytes)

    for router in (agent.router, auth.router, cameras.router, detections.router, incidents.router,
                   stats.router, uploads.router, search.router, reports.router,
                   health.router, users.router, ws_endpoint.router):
        app.include_router(router)

    # Snapshots/heatmaps served directly (nginx also serves these in production).
    # In agent/cloud mode snapshots live in S3 behind presigned GETs, so the old
    # public /media route must NOT be exposed on staging: it 404s by design.
    if not settings.agent_mode and os.path.isdir(settings.media_root):
        app.mount("/media", StaticFiles(directory=settings.media_root), name="media")

    stop_event = asyncio.Event()
    background: list[asyncio.Task] = []

    @app.on_event("startup")
    async def startup() -> None:
        await _bootstrap_admin()
        await ws_manager.start()
        background.append(asyncio.create_task(_insights_loop(stop_event)))
        if settings.agent_mode:
            background.append(asyncio.create_task(run_agent_watchdog(stop_event)))
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
