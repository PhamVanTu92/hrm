"""Approval API routes: workflow config, leave submission, and the
approve / reject / cancel actions.

Authorization:
  * approval:manage -> configure workflows, view all instances
  * approval:act    -> approve/reject a step assigned to you
  * authenticated   -> submit own leave, cancel own request, view an instance
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.pagination import Envelope, PageParams
from app.core.rbac import CurrentUser, CurrentUserDep, require_perm
from app.db.session import get_db
from app.modules.approval.repository import InstanceRepository, WorkflowRepository
from app.modules.approval.schemas import (
    ApprovalAction,
    InstanceOut,
    LeaveRequestCreate,
    WorkflowCreate,
    WorkflowOut,
)
from app.modules.approval.service import ApprovalService

router = APIRouter(prefix="/approvals", tags=["approvals"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# --------------------------------------------------------------------------- #
# Workflow config                                                             #
# --------------------------------------------------------------------------- #
@router.post(
    "/workflows", response_model=Envelope[WorkflowOut], status_code=status.HTTP_201_CREATED
)
async def create_workflow(
    payload: WorkflowCreate,
    db: DbDep,
    _: CurrentUser = require_perm("approval:manage"),
) -> Envelope[WorkflowOut]:
    workflow = await ApprovalService(db).create_workflow(
        target_type=payload.target_type,
        name=payload.name,
        steps=[s.model_dump() for s in payload.steps],
    )
    return Envelope(data=WorkflowOut.model_validate(workflow))


@router.get("/workflows", response_model=Envelope[list[WorkflowOut]])
async def list_workflows(
    db: DbDep,
    _: CurrentUser = require_perm("approval:manage"),
) -> Envelope[list[WorkflowOut]]:
    rows, _total = await WorkflowRepository(db).list_page(PageParams(size=100))
    return Envelope(data=[WorkflowOut.model_validate(w) for w in rows])


# --------------------------------------------------------------------------- #
# Leave submission                                                            #
# --------------------------------------------------------------------------- #
@router.post(
    "/leave-requests", response_model=Envelope[InstanceOut], status_code=status.HTTP_201_CREATED
)
async def submit_leave(
    payload: LeaveRequestCreate,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
) -> Envelope[InstanceOut]:
    instance = await ApprovalService(db).submit_leave(
        requester_id=user.id,
        employee_id=payload.employee_id,
        leave_type=payload.leave_type,
        start=payload.start_date,
        end=payload.end_date,
        is_paid=payload.is_paid,
        reason=payload.reason,
        ip=_ip(request),
    )
    return Envelope(data=InstanceOut.model_validate(instance))


# --------------------------------------------------------------------------- #
# Instance views                                                              #
# --------------------------------------------------------------------------- #
@router.get("/instances/{instance_id}", response_model=Envelope[InstanceOut])
async def get_instance(
    instance_id: int,
    db: DbDep,
    _: CurrentUserDep,
) -> Envelope[InstanceOut]:
    instance = await InstanceRepository(db).get(instance_id)
    if instance is None:
        raise NotFoundError("Không tìm thấy đơn duyệt")
    return Envelope(data=InstanceOut.model_validate(instance))


@router.get("/my-pending", response_model=Envelope[list[InstanceOut]])
async def my_pending(
    db: DbDep,
    user: CurrentUserDep,
) -> Envelope[list[InstanceOut]]:
    rows = await InstanceRepository(db).pending_for_approver(user.id)
    return Envelope(data=[InstanceOut.model_validate(i) for i in rows])


# --------------------------------------------------------------------------- #
# Actions                                                                     #
# --------------------------------------------------------------------------- #
@router.post("/instances/{instance_id}/approve", response_model=Envelope[InstanceOut])
async def approve(
    instance_id: int,
    payload: ApprovalAction,
    request: Request,
    db: DbDep,
    user: CurrentUser = require_perm("approval:act"),
) -> Envelope[InstanceOut]:
    instance = await ApprovalService(db).approve(
        instance_id, user, payload.comment, ip=_ip(request)
    )
    return Envelope(data=InstanceOut.model_validate(instance))


@router.post("/instances/{instance_id}/reject", response_model=Envelope[InstanceOut])
async def reject(
    instance_id: int,
    payload: ApprovalAction,
    request: Request,
    db: DbDep,
    user: CurrentUser = require_perm("approval:act"),
) -> Envelope[InstanceOut]:
    instance = await ApprovalService(db).reject(instance_id, user, payload.comment, ip=_ip(request))
    return Envelope(data=InstanceOut.model_validate(instance))


@router.post("/instances/{instance_id}/cancel", response_model=Envelope[InstanceOut])
async def cancel(
    instance_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
) -> Envelope[InstanceOut]:
    instance = await ApprovalService(db).cancel(instance_id, user, ip=_ip(request))
    return Envelope(data=InstanceOut.model_validate(instance))
