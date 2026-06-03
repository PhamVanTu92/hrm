"""Audit recorder — writes immutable audit entries within the caller's txn.

The insert is intentionally NOT committed here; it participates in the business
transaction so audit and data change are atomic.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.masking import mask
from app.audit.models import AuditLog


async def record(
    session: AsyncSession,
    *,
    actor_id: int | None,
    action: str,
    entity: str,
    entity_id: str | int | None = None,
    old: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Append an audit entry (sensitive fields masked)."""
    session.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            old_value=mask(old),
            new_value=mask(new),
            ip=ip,
            user_agent=user_agent,
        )
    )
    await session.flush()
