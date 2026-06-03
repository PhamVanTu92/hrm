"""Shared pytest fixtures.

Strategy
--------
* A real PostgreSQL 16 is started once per test session via *testcontainers*,
  and the production Alembic migrations are applied to it — so tests run against
  the exact schema (partitions, rules, extensions, blind indexes) that ships.
* Each test runs inside a single connection-bound transaction that is rolled
  back at teardown, so tests are isolated and order-independent without
  re-migrating between them.
* The rate limiter is disabled (no Redis needed); authorization is exercised by
  minting real JWTs with explicit permission sets.

Required env vars are set BEFORE importing any ``app`` module, because
``app.core.config`` validates settings at import time.
"""

from __future__ import annotations

import os

# ---- Must run before importing anything from `app` ----
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-at-least-32-characters-long-xx")
os.environ.setdefault("AES_KEY_HEX", "a" * 64)
os.environ.setdefault("BLIND_INDEX_KEY_HEX", "b" * 64)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RATE_LIMIT_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/2")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/3")

from collections.abc import AsyncGenerator, Callable  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.rbac import PERMISSIONS, ROLE_PERMISSIONS  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.middleware.rate_limit import limiter  # noqa: E402
from app.modules.auth.models import Permission, Role, User  # noqa: E402

# No Redis in tests — slowapi short-circuits when disabled.
limiter.enabled = False

BACKEND_DIR = Path(__file__).resolve().parent.parent
API = settings.API_V1_PREFIX


# --------------------------------------------------------------------------- #
# Database (session scope, synchronous setup)                                 #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def database_url() -> str:
    """Start Postgres, point settings at it, apply migrations. Returns async DSN."""
    with PostgresContainer("postgres:16-alpine") as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        async_url = f"postgresql+asyncpg://{pg.username}:{pg.password}@{host}:{port}/{pg.dbname}"
        # Patch the settings singleton so Alembic's env.py (which reads
        # settings.sync_database_url) targets the container.
        settings.DATABASE_URL = async_url  # type: ignore[assignment]

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        command.upgrade(cfg, "head")

        yield async_url


@pytest_asyncio.fixture
async def db_session(database_url: str) -> AsyncGenerator[AsyncSession, None]:
    """Per-test session bound to a transaction that is rolled back at teardown."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    conn = await engine.connect()
    trans = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        if trans.is_active:
            await trans.rollback()
        await conn.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client whose requests share the test's transaction-bound session."""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# RBAC / user helpers                                                         #
# --------------------------------------------------------------------------- #
async def seed_rbac(session: AsyncSession) -> None:
    """Insert the full permission catalog and default roles."""
    for code in sorted(PERMISSIONS):
        session.add(Permission(code=code, name=code))
    await session.flush()
    perms = {p.code: p for p in (await session.execute(select(Permission))).scalars().all()}
    for role_code, codes in ROLE_PERMISSIONS.items():
        role = Role(code=role_code, name=role_code, is_system=True)
        role.permissions = [perms[c] for c in codes]
        session.add(role)
    await session.flush()


async def create_user(
    session: AsyncSession, *, username: str, password: str, role_codes: list[str]
) -> User:
    """Create a user with the given roles (RBAC must be seeded first)."""
    roles = (await session.execute(select(Role).where(Role.code.in_(role_codes)))).scalars().all()
    user = User(
        username=username,
        email=f"{username}@test.vn",
        password_hash=hash_password(password),
        roles=list(roles),
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncSession:
    """db_session with the RBAC catalog seeded."""
    await seed_rbac(db_session)
    return db_session


@pytest.fixture
def auth_header() -> Callable[..., dict[str, str]]:
    """Factory minting an Authorization header with explicit roles/permissions."""

    def _make(
        *, sub: int = 1, roles: list[str] | None = None, perms: list[str] | None = None
    ) -> dict[str, str]:
        token = create_access_token(subject=sub, roles=roles or [], permissions=sorted(perms or []))
        return {"Authorization": f"Bearer {token}"}

    return _make
