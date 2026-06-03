"""Async SQLAlchemy engine + session management.

Provides:
- A primary engine for reads + writes.
- An optional read-replica engine for read-heavy queries.
- ``get_db`` FastAPI dependency yielding a session with commit/rollback.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# ---- Primary engine (read/write) ----
engine: AsyncEngine = create_async_engine(
    str(settings.DATABASE_URL),
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)

# ---- Optional read replica ----
if settings.DATABASE_REPLICA_URL:
    replica_engine: AsyncEngine = create_async_engine(
        str(settings.DATABASE_REPLICA_URL),
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=1800,
    )
    ReplicaSessionLocal = async_sessionmaker(
        bind=replica_engine, expire_on_commit=False, autoflush=False
    )
else:
    replica_engine = engine
    ReplicaSessionLocal = SessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield a transactional session.

    Commits on success, rolls back on exception, always closes.
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for read-only queries (uses replica if configured)."""
    async with ReplicaSessionLocal() as session:
        yield session


async def dispose_engines() -> None:
    """Dispose engine pools at shutdown."""
    await engine.dispose()
    if replica_engine is not engine:
        await replica_engine.dispose()
