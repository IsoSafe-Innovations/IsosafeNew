import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, require_admin, write_audit
from app.api.types import EmailAddress
from app.db.engine import get_engine
from app.db.tables import users
from app.security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])

ROLES = {"admin", "operator", "viewer"}


class UserCreate(BaseModel):
    email: EmailAddress
    password: str
    role: str


class UserPatch(BaseModel):
    password: str | None = None
    role: str | None = None


@router.get("")
async def list_users(user: CurrentUser = Depends(require_admin)) -> list[dict]:
    engine = get_engine()
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.select(users.c.id, users.c.email, users.c.role, users.c.created_at)
            )
        ).mappings().all()
    return [
        {**dict(r), "id": str(r["id"]),
         "created_at": r["created_at"].isoformat() if r["created_at"] else None}
        for r in rows
    ]


@router.post("", status_code=201)
async def create_user(body: UserCreate, user: CurrentUser = Depends(require_admin)) -> dict:
    if body.role not in ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(ROLES)}")
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    engine = get_engine()
    email = body.email.lower()
    async with engine.begin() as conn:
        existing = (
            await conn.execute(sa.select(users.c.id).where(users.c.email == email))
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already exists")
        user_id = uuid.uuid4()
        await conn.execute(
            sa.insert(users).values(
                id=user_id, email=email,
                password_hash=hash_password(body.password), role=body.role,
            )
        )
    await write_audit(user.email, "user.create", email, {"role": body.role})
    return {"id": str(user_id), "email": email, "role": body.role}


@router.patch("/{user_id}")
async def patch_user(
    user_id: uuid.UUID, body: UserPatch, user: CurrentUser = Depends(require_admin)
) -> dict:
    updates: dict = {}
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(status_code=422, detail=f"role must be one of {sorted(ROLES)}")
        updates["role"] = body.role
    if body.password is not None:
        if len(body.password) < 8:
            raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
        updates["password_hash"] = hash_password(body.password)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            sa.update(users).where(users.c.id == user_id).values(**updates)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        row = (
            await conn.execute(
                sa.select(users.c.id, users.c.email, users.c.role).where(users.c.id == user_id)
            )
        ).mappings().one()
    await write_audit(user.email, "user.update", str(user_id),
                      {"role": body.role} if body.role else {"password": "***"})
    return {**dict(row), "id": str(row["id"])}


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: uuid.UUID, user: CurrentUser = Depends(require_admin)) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(sa.delete(users).where(users.c.id == user_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="User not found")
    await write_audit(user.email, "user.delete", str(user_id))
