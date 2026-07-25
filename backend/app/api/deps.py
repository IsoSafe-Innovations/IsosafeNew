"""Auth dependencies, role enforcement, Redis rate limiting, audit logging."""
import logging
from dataclasses import dataclass

import jwt as pyjwt
import sqlalchemy as sa
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db.engine import get_engine
from app.db.tables import audit_log
from app.redis_client import get_redis
from app.security import decode_token

log = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)

ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}


@dataclass
class CurrentUser:
    email: str
    role: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return CurrentUser(email=payload["sub"], role=payload["role"])


def require_role(minimum: str):
    """FastAPI dependency enforcing a minimum role."""

    async def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if ROLE_RANK.get(user.role, -1) < ROLE_RANK[minimum]:
            raise HTTPException(status_code=403, detail=f"Requires {minimum} role")
        return user

    return checker


require_viewer = require_role("viewer")
require_operator = require_role("operator")
require_admin = require_role("admin")


async def rate_limit(request: Request, key: str, limit: int, window_secs: int) -> None:
    """Sliding-window-ish rate limit via Redis INCR + EXPIRE."""
    client_ip = request.client.host if request.client else "unknown"
    redis_key = f"isosafe:rl:{key}:{client_ip}"
    r = get_redis()
    count = await r.incr(redis_key)
    if count == 1:
        await r.expire(redis_key, window_secs)
    if count > limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded, slow down")


def rate_limited(key: str, limit: int, window_secs: int):
    async def dep(request: Request) -> None:
        await rate_limit(request, key, limit, window_secs)

    return dep


async def write_audit(user_email: str, action: str, target: str, payload: dict | None = None):
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(audit_log).values(
                    user_email=user_email, action=action, target=target, payload=payload
                )
            )
    except Exception:
        log.exception("audit write failed")
