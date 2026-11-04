import hashlib
import io
import tarfile
from unittest.mock import Mock

import pytest
from fastapi import Response

from scripts import aws_ops


def test_backup_age_missing_and_future_are_safe(tmp_path):
    stamp = tmp_path / "stamp"
    assert aws_ops.age_hours(stamp, now=7200) > 7
    stamp.write_text("3600")
    assert aws_ops.age_hours(stamp, now=7200) == 1
    stamp.write_text("10000")
    assert aws_ops.age_hours(stamp, now=7200) == 0


def test_extract_db_does_not_extract_runtime_secrets(tmp_path):
    bundle = tmp_path / "backup.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        for name, content in (("database.dump", b"test-db"), ("runtime.env", b"SECRET=private")):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    target = tmp_path / "restored.dump"
    aws_ops.extract_database(bundle, target)
    assert target.read_bytes() == b"test-db"
    assert not (tmp_path / "runtime.env").exists()


def test_extract_db_rejects_symlink(tmp_path):
    bundle = tmp_path / "backup.tar.gz"
    with tarfile.open(bundle, "w:gz") as archive:
        member = tarfile.TarInfo("database.dump")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        archive.addfile(member)
    with pytest.raises(ValueError):
        aws_ops.extract_database(bundle, tmp_path / "restored.dump")


def test_download_rejects_corrupt_backup(tmp_path, monkeypatch):
    client = Mock()
    client.head_object.return_value = {"Metadata": {"sha256": hashlib.sha256(b"valid").hexdigest()}}
    client.download_file.side_effect = lambda bucket, key, path: open(path, "wb").write(b"corrupt")
    monkeypatch.setattr(aws_ops, "s3_client", lambda: client)
    monkeypatch.setenv("BACKUP_BUCKET", "test")
    with pytest.raises(RuntimeError, match="checksum"):
        aws_ops.download("backups/test.tar.gz", str(tmp_path / "download"))


def test_upload_verifies_remote_backup_before_success(tmp_path, monkeypatch):
    source = tmp_path / "backup.tar.gz"
    source.write_bytes(b"backup")
    client = Mock()
    client.head_object.return_value = {"ContentLength": 6, "Metadata": {"sha256": "wrong"}}
    monkeypatch.setattr(aws_ops, "s3_client", lambda: client)
    monkeypatch.setenv("BACKUP_BUCKET", "test")
    with pytest.raises(RuntimeError, match="verification"):
        aws_ops.upload(source)


@pytest.mark.asyncio
async def test_unhealthy_api_returns_503_without_connection_secrets(monkeypatch):
    from app.api import health

    def broken():
        raise RuntimeError("postgresql://user:secret@private-host/db")

    monkeypatch.setattr(health, "get_engine", broken)
    monkeypatch.setattr(health, "get_redis", broken)
    response = Response()
    result = await health.health(response)
    assert response.status_code == 503
    assert result["status"] == "degraded"
    assert "secret" not in str(result)
    assert "private-host" not in str(result)
