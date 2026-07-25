"""Async database engine plus a raw asyncpg pool for high-throughput batch writes."""
import asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
_pool: asyncpg.Pool | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
    return _engine


async def get_asyncpg_pool() -> asyncpg.Pool:
    """Raw pool used by the detection batch writer (executemany) and NL search."""
    global _pool
    if _pool is None:
        dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    return _pool


async def dispose() -> None:
    global _engine, _pool
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    if _pool is not None:
        await _pool.close()
        _pool = None
