"""Website uploads: real multipart requests and video decoding, isolated DB writes."""
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api import cameras as cameras_api, uploads
from app.api.deps import CurrentUser, get_current_user
from app.config import get_settings


class Database:
    def __init__(self):
        self.statements = []
        self.count = 0
        self.fail_insert = False

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement):
        if self.fail_insert and statement.is_insert:
            raise RuntimeError("database unavailable")
        self.statements.append(statement)
        return SimpleNamespace(scalar_one=lambda: self.count)

    def inserts(self, table):
        return [s.compile().params for s in self.statements
                if s.is_insert and s.table.name == table]


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    monkeypatch.setenv("DISK_MIN_FREE_GB", "0")
    monkeypatch.setenv("UPLOAD_MAX_MB", "1")
    monkeypatch.setenv("MAX_CAMERAS_PER_NODE", "2")
    get_settings.cache_clear()
    db = Database()
    monkeypatch.setattr(uploads, "get_engine", lambda: db)

    async def audit(*args):
        pass

    monkeypatch.setattr(uploads, "write_audit", audit)
    app = FastAPI()
    app.include_router(uploads.router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser("operator@example.com", "operator")
    client = TestClient(app, raise_server_exceptions=False)
    yield client, db, app, tmp_path / "media" / "uploads"
    get_settings.cache_clear()


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    assert writer.isOpened()
    for _ in range(10):
        writer.write(np.full((48, 64, 3), 80, dtype=np.uint8))
    writer.release()
    return path.read_bytes()


def test_upload_creates_looping_named_camera(setup, video):
    client, db, _, directory = setup
    response = client.post("/api/uploads", files={"file": ("../entrance.MP4", video)},
                           data={"name": " Entrance replay "})
    assert response.status_code == 202, response.text
    result = response.json()
    camera, = db.inserts("cameras")
    job, = db.inserts("upload_jobs")
    assert camera["id"] == result["camera_id"] == job["camera_id"]
    assert camera["name"] == "Entrance replay"
    assert camera["type"] == "file" and camera["loop_file"] is True and camera["enabled"] is True
    assert job["filename"] == "entrance.MP4"
    assert job["status"] == result["status"] == "ready"
    saved, = directory.iterdir()
    assert saved.read_bytes() == video
    assert str(saved) == camera["source"]


def test_upload_default_name_and_unique_paths(setup, video):
    client, db, _, directory = setup
    for _ in range(2):
        assert client.post("/api/uploads", files={"file": ("entrance.mp4", video)}).status_code == 202
    first, second = db.inserts("cameras")
    assert first["name"] == second["name"] == "entrance"
    assert first["id"] != second["id"] and first["source"] != second["source"]
    assert len(list(directory.iterdir())) == 2


@pytest.mark.parametrize("filename,data,status", [
    ("recording.txt", b"text", 422), ("empty.mp4", b"", 422),
    ("fake.mp4", b"not video", 422), ("large.mp4", b"0" * (1024 * 1024 + 1), 413),
], ids=["unsupported-type", "empty", "corrupt", "oversized"])
def test_invalid_upload_leaves_no_camera_or_file(setup, filename, data, status):
    client, db, _, directory = setup
    response = client.post("/api/uploads", files={"file": (filename, data)})
    assert response.status_code == status, response.text
    assert not db.inserts("cameras") and not db.inserts("upload_jobs")
    assert not directory.exists() or not list(directory.iterdir())


def test_capacity_rejection_cleans_up(setup, video):
    client, db, _, directory = setup
    db.count = 2
    response = client.post("/api/uploads", files={"file": ("recording.mp4", video)})
    assert response.status_code == 409
    assert not list(directory.iterdir()) and not db.inserts("cameras")


def test_database_failure_cleans_up(setup, video):
    client, db, _, directory = setup
    db.fail_insert = True
    response = client.post("/api/uploads", files={"file": ("recording.mp4", video)})
    assert response.status_code == 500
    assert not list(directory.iterdir())


def test_disk_full_cleans_up(setup, video, monkeypatch):
    client, db, _, directory = setup
    monkeypatch.setattr(uploads.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    response = client.post("/api/uploads", files={"file": ("recording.mp4", video)})
    assert response.status_code == 507
    assert not list(directory.iterdir()) and not db.inserts("cameras")


def test_config_and_permissions(setup, video):
    client, db, app, _ = setup
    assert client.get("/api/uploads/config").json()["max_mb"] == 1
    app.dependency_overrides[get_current_user] = lambda: CurrentUser("viewer@example.com", "viewer")
    assert client.get("/api/uploads/config").status_code == 403
    assert client.post("/api/uploads", files={"file": ("video.mp4", video)}).status_code == 403
    app.dependency_overrides.clear()
    assert client.post("/api/uploads", files={"file": ("video.mp4", video)}).status_code == 401
    assert not db.statements


async def test_worker_selects_uploaded_cameras_only(monkeypatch):
    from app.pipeline.runner import Pipeline

    monkeypatch.setenv("AGENT_MODE", "0")
    monkeypatch.setenv("PIPELINE_UPLOADS_ONLY", "1")
    get_settings.cache_clear()
    statements = []

    class Connection(Database):
        def connect(self):
            return self

        async def execute(self, statement):
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))

    monkeypatch.setattr("app.pipeline.runner.get_engine", Connection)
    try:
        assert await Pipeline()._camera_rows() == []
        assert "cameras.id IN (SELECT upload_jobs.camera_id" in statements[0]
        from app.sinks.factory import get_frame_sink, get_incident_sink
        from app.sinks.frames import LocalRedisFrameSink
        from app.sinks.incidents import CloudIncidentSink
        assert isinstance(get_frame_sink(), LocalRedisFrameSink)
        assert isinstance(get_incident_sink(), CloudIncidentSink)
    finally:
        get_settings.cache_clear()


async def test_site_agent_excludes_upload_paths(monkeypatch):
    from app.api import agent

    statements = []

    class Connection(Database):
        def connect(self):
            return self

        async def execute(self, statement):
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))

    monkeypatch.setattr(agent, "get_engine", Connection)
    monkeypatch.setattr(agent, "_require_agent_auth", lambda _: None)
    assert (await agent.get_config(None))["cameras"] == []
    assert "NOT (EXISTS (SELECT upload_jobs.id" in statements[0]
    assert "upload_jobs.camera_id = cameras.id" in statements[0]


async def test_deleting_upload_removes_only_its_generated_file(monkeypatch, tmp_path):
    import uuid

    job_id = uuid.uuid4()
    directory = tmp_path / "uploads"
    directory.mkdir()
    uploaded = directory / f"{job_id}.mp4"
    uploaded.write_bytes(b"video")
    other = directory / "other.mp4"
    other.write_bytes(b"keep")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path))
    get_settings.cache_clear()

    class Connection(Database):
        async def execute(self, statement):
            return SimpleNamespace(rowcount=1, mappings=lambda: SimpleNamespace(all=lambda: [
                {"id": job_id, "filename": "../../recording.mp4"},
            ]))

    async def audit(*args):
        pass

    monkeypatch.setattr(cameras_api, "get_engine", Connection)
    monkeypatch.setattr(cameras_api, "write_audit", audit)
    try:
        await cameras_api.delete_camera("uploaded-camera", CurrentUser("admin@example.com", "admin"))
        assert not uploaded.exists() and other.read_bytes() == b"keep"
    finally:
        get_settings.cache_clear()
