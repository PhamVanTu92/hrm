"""Tests for the audit read API + repository."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.audit.repository import AuditRepository
from app.core.pagination import PageParams
from tests.conftest import API

HeaderFactory = Callable[..., dict[str, str]]


async def _log(
    session: AsyncSession,
    *,
    action: str,
    entity: str,
    entity_id: str,
    actor_id: int,
    when: datetime,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            created_at=when,
        )
    )
    await session.flush()


async def _seed_logs(session: AsyncSession) -> datetime:
    base = datetime(2026, 5, 10, 9, 0, tzinfo=UTC)
    await _log(session, action="CREATE", entity="employees", entity_id="1", actor_id=10, when=base)
    await _log(
        session,
        action="UPDATE",
        entity="employees",
        entity_id="1",
        actor_id=11,
        when=base + timedelta(hours=1),
    )
    await _log(
        session,
        action="VIEW_SENSITIVE",
        entity="employees",
        entity_id="2",
        actor_id=10,
        when=base + timedelta(days=2),
    )
    return base


# --------------------------------------------------------------------------- #
# Repository                                                                  #
# --------------------------------------------------------------------------- #
async def test_filter_by_entity_id(db_session: AsyncSession) -> None:
    await _seed_logs(db_session)
    rows, total = await AuditRepository(db_session).query(
        PageParams(), entity="employees", entity_id="1"
    )
    assert total == 2
    assert {r.action for r in rows} == {"CREATE", "UPDATE"}


async def test_filter_by_actor(db_session: AsyncSession) -> None:
    await _seed_logs(db_session)
    _rows, total = await AuditRepository(db_session).query(PageParams(), actor_id=10)
    assert total == 2


async def test_time_range_prunes(db_session: AsyncSession) -> None:
    base = await _seed_logs(db_session)
    # Only the first day -> excludes the +2 days VIEW_SENSITIVE row.
    _rows, total = await AuditRepository(db_session).query(
        PageParams(), date_from=base, date_to=base + timedelta(hours=12)
    )
    assert total == 2


async def test_newest_first(db_session: AsyncSession) -> None:
    await _seed_logs(db_session)
    rows, _total = await AuditRepository(db_session).query(PageParams())
    times = [r.created_at for r in rows]
    assert times == sorted(times, reverse=True)


# --------------------------------------------------------------------------- #
# API + RBAC                                                                  #
# --------------------------------------------------------------------------- #
async def test_audit_api_requires_perm(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    await _seed_logs(db_session)
    forbidden = await client.get(f"{API}/audit/logs", headers=auth_header(perms=["employee:read"]))
    assert forbidden.status_code == 403

    ok = await client.get(
        f"{API}/audit/logs",
        params={"entity": "employees", "entity_id": "1"},
        headers=auth_header(perms=["audit:read"]),
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 2


async def test_audit_api_unauthenticated(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/audit/logs")).status_code == 401
