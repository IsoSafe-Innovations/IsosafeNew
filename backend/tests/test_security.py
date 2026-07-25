import jwt as pyjwt
import pytest
from cryptography.fernet import Fernet

from app.config import get_settings
from app.security import (create_token, decode_token, decrypt_source,
                          encrypt_source, hash_password, redact_source,
                          verify_password)


def test_password_roundtrip():
    h = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    token = create_token("op@example.com", "operator", "access")
    payload = decode_token(token, "access")
    assert payload["sub"] == "op@example.com"
    assert payload["role"] == "operator"


def test_refresh_token_rejected_as_access():
    token = create_token("op@example.com", "operator", "refresh")
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token(token, "access")


def test_tampered_token_rejected():
    token = create_token("op@example.com", "viewer", "access")
    with pytest.raises(pyjwt.PyJWTError):
        decode_token(token + "x", "access")


def test_source_encryption_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode()
    get_settings.cache_clear()
    monkeypatch.setenv("FERNET_KEY", key)
    try:
        rtsp = "rtsp://admin:hunter2@10.0.0.5:554/stream1"
        stored = encrypt_source(rtsp)
        assert stored.startswith("enc:")
        assert "hunter2" not in stored
        assert decrypt_source(stored) == rtsp
        assert "hunter2" not in redact_source(stored)
        assert "10.0.0.5" in redact_source(stored)
    finally:
        get_settings.cache_clear()


def test_no_key_passthrough(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.delenv("FERNET_KEY", raising=False)
    try:
        assert encrypt_source("file:///demo.mp4") == "file:///demo.mp4"
        assert decrypt_source("file:///demo.mp4") == "file:///demo.mp4"
    finally:
        get_settings.cache_clear()
