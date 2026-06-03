"""Read-side access for the immutable audit log.

Queries always allow a time range so PostgreSQL can prune partitions; an index
on ``(entity, entity_id, created_at DESC)`` makes single-record history fast.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.core.pagination import PageParams


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def query(
        self,
        params: PageParams,
        *,
        entity: str | None = None,
        entity_id: str | None = None,
        actor_id: int | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[AuditLog], int]:
        stmt = select(AuditLog)
        if entity is not None:
            stmt = stmt.where(AuditLog.entity == entity)
        if entity_id is not None:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if date_from is not None:
            stmt = stmt.where(AuditLog.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(AuditLog.created_at <= date_to)

        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        stmt = stmt.order_by(AuditLog.created_at.desc()).offset(params.offset).limit(params.size)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total
