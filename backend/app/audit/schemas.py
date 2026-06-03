"""Schemas for the audit read API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    actor_id: int | None
    action: str
    entity: str
    entity_id: str | None
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    ip: str | None
    user_agent: str | None


class AuditFilter(BaseModel):
    entity: str | None = None
    entity_id: str | None = None
    actor_id: int | None = None
    action: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


def audit_filter(
    entity: Annotated[str | None, Query()] = None,
    entity_id: Annotated[str | None, Query()] = None,
    actor_id: Annotated[int | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    date_from: Annotated[datetime | None, Query(description="ISO datetime, lower bound")] = None,
    date_to: Annotated[datetime | None, Query(description="ISO datetime, upper bound")] = None,
) -> AuditFilter:
    return AuditFilter(
        entity=entity,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
