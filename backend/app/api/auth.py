import logging

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import jwt as pyjwt

from app.api.deps import rate_limited
from app.api.types import EmailAddress
from app.db.engine import get_engine
from app.db.tables import users
from app.security import create_token, decode_token, verify_password

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailAddress
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    role: str
    email: str


@router.post("/login", response_model=TokenResponse,
             dependencies=[Depends(rate_limited("login", limit=10, window_secs=60))])
async def login(body: LoginRequest) -> TokenResponse:
    engine = get_engine()
    async with engine.connect() as conn:
        row = (
            await conn.execute(sa.select(users).where(users.c.email == body.email.lower()))
        ).mappings().first()
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(
        access_token=create_token(row["email"], row["role"], "access"),
        refresh_token=create_token(row["email"], row["role"], "refresh"),
        role=row["role"],
        email=row["email"],
    )


@router.post("/refresh", response_model=TokenResponse,
             dependencies=[Depends(rate_limited("refresh", limit=30, window_secs=60))])
async def refresh(body: RefreshRequest) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    # re-check the user still exists and pick up role changes
    engine = get_engine()
    async with engine.connect() as conn:
        row = (
            await conn.execute(sa.select(users).where(users.c.email == payload["sub"]))
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return TokenResponse(
        access_token=create_token(row["email"], row["role"], "access"),
        refresh_token=create_token(row["email"], row["role"], "refresh"),
        role=row["role"],
        email=row["email"],
    )
