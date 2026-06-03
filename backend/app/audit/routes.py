"""Audit log read API.

Read-only. Restricted to ``audit:read`` (typically ADMIN). The log itself is
immutable at the DB level — there is no write/update/delete endpoint by design.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.repository import AuditRepository
from app.audit.schemas import AuditFilter, AuditLogOut, audit_filter
from app.core.pagination import Page, PageParams, page_params
from app.core.rbac import CurrentUser, require_perm
from app.db.session import get_db

router = APIRouter(prefix="/audit", tags=["audit"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("/logs", response_model=Page[AuditLogOut])
async def list_audit_logs(
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    filters: Annotated[AuditFilter, Depends(audit_filter)],
    _: CurrentUser = require_perm("audit:read"),
) -> Page[AuditLogOut]:
    """Query the audit trail. Always pass a time range for partition pruning."""
    rows, total = await AuditRepository(db).query(
        params,
        entity=filters.entity,
        entity_id=filters.entity_id,
        actor_id=filters.actor_id,
        action=filters.action,
        date_from=filters.date_from,
        date_to=filters.date_to,
    )
    return Page.create([AuditLogOut.model_validate(r) for r in rows], total, params)
