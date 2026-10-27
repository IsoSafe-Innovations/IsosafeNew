"""Password hashing, JWT issuing/verification, and at-rest encryption for camera credentials."""
import datetime as dt
import uuid

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

ALGO = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(email: str, role: str, token_type: str) -> str:
    s = get_settings()
    now = dt.datetime.now(dt.UTC)
    if token_type == "access":
        exp = now + dt.timedelta(minutes=s.access_token_minutes)
    else:
        exp = now + dt.timedelta(days=s.refresh_token_days)
    payload = {
        "sub": email,
        "role": role,
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGO)


def decode_token(token: str, expected_type: str = "access") -> dict:
    """Raises jwt.PyJWTError on any failure."""
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGO])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected {expected_type} token")
    return payload


# --- Camera source encryption (RTSP credentials at rest) ---

_PREFIX = "enc:"


def _fernet() -> Fernet | None:
    key = get_settings().fernet_key
    return Fernet(key.encode()) if key else None


def encrypt_source(source: str) -> str:
    f = _fernet()
    if f is None:
        return source
    return _PREFIX + f.encrypt(source.encode()).decode()


def decrypt_source(stored: str) -> str:
    if not stored.startswith(_PREFIX):
        return stored
    f = _fernet()
    if f is None:
        raise RuntimeError("FERNET_KEY not set but camera source is encrypted")
    try:
        return f.decrypt(stored[len(_PREFIX):].encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("failed to decrypt camera source") from e


def redact_source(stored: str) -> str:
    """Return a display-safe version of the source (credentials stripped)."""
    try:
        source = decrypt_source(stored)
    except RuntimeError:
        return "<encrypted>"
    if "@" in source and "://" in source:
        scheme, rest = source.split("://", 1)
        if "@" in rest:
            rest = rest.split("@", 1)[1]
            return f"{scheme}://***@{rest}"
    return source
