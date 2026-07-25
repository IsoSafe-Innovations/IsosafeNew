"""Reset bootstrap admin password. Usage: python -m scripts.reset_admin [email] [password]"""
import asyncio
import sys

import sqlalchemy as sa

from app.db.engine import get_engine
from app.db.tables import users
from app.security import hash_password


async def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else "admin@isosafe.local"
    password = sys.argv[2] if len(sys.argv) > 2 else "admin123"
    engine = get_engine()
    async with engine.begin() as conn:
        row = (
            await conn.execute(sa.select(users).where(users.c.email == email))
        ).mappings().first()
        if row is None:
            print(f"No user {email!r}")
            return
        await conn.execute(
            sa.update(users)
            .where(users.c.email == email)
            .values(password_hash=hash_password(password))
        )
    print(f"Password reset for {email}")


if __name__ == "__main__":
    asyncio.run(main())
