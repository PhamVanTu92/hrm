"""Tests for the approval workflow engine.

Service-level tests cover the state machine, dynamic approver resolution and
SLA escalation; one test follows the full chain through to attendance
compensation (the cross-module integration). A few API tests cover RBAC.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, PermissionDenied
from app.core.rbac import CurrentUser
from app.modules.approval.models import (
    ApprovalStepInstance,
    ApproverType,
    InstanceStatus,
    LeaveStatus,
)
from app.modules.approval.service import ApprovalService
from app.modules.attendance.models import AttendanceDaily, DailyStatus
from app.modules.employee.models import Employee
from tests.conftest import API, create_user

HeaderFactory = Callable[..., dict[str, str]]
LEAVE_DAY = date(2026, 5, 11)


# --------------------------------------------------------------------------- #
# Org + workflow scaffolding                                                  #
# --------------------------------------------------------------------------- #
async def _employee(
    session: AsyncSession, code: str, *, user_id: int | None = None, manager_id: int | None = None
) -> Employee:
    emp = Employee(employee_code=code, full_name=code, user_id=user_id, manager_id=manager_id)
    session.add(emp)
    await session.flush()
    return emp


async def _two_step_workflow(session: AsyncSession) -> None:
    """MANAGER -> ROLE:HR, the canonical leave approval chain."""
    await ApprovalService(session).create_workflow(
        target_type="LEAVE",
        name="Nghỉ phép",
        steps=[
            {"approver_type": ApproverType.MANAGER, "sla_hours": 24},
            {"approver_type": ApproverType.ROLE, "approver_ref": "HR", "sla_hours": 48},
        ],
    )


async def _org(session: AsyncSession) -> dict:
    """Build manager + HR users and a subordinate employee. Returns key ids."""
    manager_user = await create_user(session, username="mgr", password="x", role_codes=["MANAGER"])
    hr_user = await create_user(session, username="hr", password="x", role_codes=["HR"])
    requester_user = await create_user(
        session, username="emp", password="x", role_codes=["EMPLOYEE"]
    )
    manager_emp = await _employee(session, "M001", user_id=manager_user.id)
    sub_emp = await _employee(session, "E001", user_id=requester_user.id, manager_id=manager_emp.id)
    return {
        "manager_user_id": manager_user.id,
        "hr_user_id": hr_user.id,
        "requester_user_id": requester_user.id,
        "employee_id": sub_emp.id,
    }


async def _submit(session: AsyncSession, org: dict):  # noqa: ANN201
    return await ApprovalService(session).submit_leave(
        requester_id=org["requester_user_id"],
        employee_id=org["employee_id"],
        leave_type="ANNUAL",
        start=LEAVE_DAY,
        end=LEAVE_DAY,
        is_paid=True,
        reason="Về quê",
    )


def _actor(user_id: int) -> CurrentUser:
    return CurrentUser(id=user_id, perms={"approval:act"})


# --------------------------------------------------------------------------- #
# Submission + approver resolution                                            #
# --------------------------------------------------------------------------- #
async def test_submit_resolves_approvers_and_starts_first_sla(
    seeded: AsyncSession,
) -> None:
    await _two_step_workflow(seeded)
    org = await _org(seeded)
    instance = await _submit(seeded, org)

    assert instance.status == InstanceStatus.PENDING
    assert instance.current_step == 1
    steps = sorted(instance.steps, key=lambda s: s.step_order)
    assert steps[0].approver_user_id == org["manager_user_id"]
    assert steps[1].approver_user_id == org["hr_user_id"]
    # Only the first step's SLA clock is running.
    assert steps[0].due_at is not None
    assert steps[1].due_at is None


async def test_submit_without_workflow_rejected(seeded: AsyncSession) -> None:
    from app.core.exceptions import ValidationError

    org = await _org(seeded)  # no workflow configured
    with pytest.raises(ValidationError):
        await _submit(seeded, org)


# --------------------------------------------------------------------------- #
# Full approval chain -> event -> attendance compensation                     #
# --------------------------------------------------------------------------- #
async def test_full_approval_compensates_attendance(seeded: AsyncSession) -> None:
    await _two_step_workflow(seeded)
    org = await _org(seeded)
    svc = ApprovalService(seeded)
    instance = await _submit(seeded, org)

    # Step 1: manager approves -> advances, not yet final.
    await svc.approve(instance.id, _actor(org["manager_user_id"]), "OK")
    assert instance.status == InstanceStatus.IN_PROGRESS
    assert instance.current_step == 2

    # Step 2: HR approves -> APPROVED + LeaveApproved published.
    await svc.approve(instance.id, _actor(org["hr_user_id"]), "Đồng ý")
    assert instance.status == InstanceStatus.APPROVED
    assert instance.completed_at is not None

    # Leave request marked approved.
    leave = await svc.leaves.get(instance.target_id)
    assert leave is not None and leave.status == LeaveStatus.APPROVED

    # Cross-module: attendance for the leave day is now compensated as LEAVE.
    daily = (
        await seeded.execute(
            select(AttendanceDaily).where(
                AttendanceDaily.employee_id == org["employee_id"],
                AttendanceDaily.work_date == LEAVE_DAY,
            )
        )
    ).scalar_one()
    assert daily.status == DailyStatus.LEAVE
    assert str(daily.work_value) == "1.00"


# --------------------------------------------------------------------------- #
# Reject / cancel / authorization                                             #
# --------------------------------------------------------------------------- #
async def test_reject_sets_rejected(seeded: AsyncSession) -> None:
    await _two_step_workflow(seeded)
    org = await _org(seeded)
    svc = ApprovalService(seeded)
    instance = await _submit(seeded, org)

    await svc.reject(instance.id, _actor(org["manager_user_id"]), "Thiếu thông tin")
    assert instance.status == InstanceStatus.REJECTED
    leave = await svc.leaves.get(instance.target_id)
    assert leave is not None and leave.status == LeaveStatus.REJECTED


async def test_approve_by_wrong_user_forbidden(seeded: AsyncSession) -> None:
    await _two_step_workflow(seeded)
    org = await _org(seeded)
    svc = ApprovalService(seeded)
    instance = await _submit(seeded, org)
    # HR is step 2, cannot approve step 1.
    with pytest.raises(PermissionDenied):
        await svc.approve(instance.id, _actor(org["hr_user_id"]), "nope")


async def test_cancel_only_by_requester(seeded: AsyncSession) -> None:
    await _two_step_workflow(seeded)
    org = await _org(seeded)
    svc = ApprovalService(seeded)
    instance = await _submit(seeded, org)

    # A non-requester cannot cancel.
    with pytest.raises(PermissionDenied):
        await svc.cancel(instance.id, _actor(org["manager_user_id"]))

    # The requester can.
    await svc.cancel(instance.id, CurrentUser(id=org["requester_user_id"], perms=set()))
    assert instance.status == InstanceStatus.CANCELLED


async def test_cannot_act_on_completed_instance(seeded: AsyncSession) -> None:
    await _two_step_workflow(seeded)
    org = await _org(seeded)
    svc = ApprovalService(seeded)
    instance = await _submit(seeded, org)
    await svc.reject(instance.id, _actor(org["manager_user_id"]), "no")
    # Already REJECTED -> further actions conflict.
    with pytest.raises(ConflictError):
        await svc.approve(instance.id, _actor(org["manager_user_id"]), "late")


# --------------------------------------------------------------------------- #
# Escalation                                                                  #
# --------------------------------------------------------------------------- #
async def test_escalate_overdue_reassigns(seeded: AsyncSession) -> None:
    await _two_step_workflow(seeded)
    org = await _org(seeded)
    svc = ApprovalService(seeded)
    instance = await _submit(seeded, org)

    # Force step 1 past its SLA deadline.
    step1 = (
        await seeded.execute(
            select(ApprovalStepInstance).where(
                ApprovalStepInstance.instance_id == instance.id,
                ApprovalStepInstance.step_order == 1,
            )
        )
    ).scalar_one()
    step1.due_at = datetime.now(UTC) - timedelta(hours=1)
    await seeded.flush()

    escalated = await svc.escalate_overdue()
    assert escalated == 1

    await seeded.refresh(step1)
    # Manager has no manager -> escalates to the HR fallback.
    assert step1.approver_user_id == org["hr_user_id"]
    assert step1.escalated is True


async def test_no_escalation_when_within_sla(seeded: AsyncSession) -> None:
    await _two_step_workflow(seeded)
    org = await _org(seeded)
    svc = ApprovalService(seeded)
    await _submit(seeded, org)  # step 1 due in 24h
    assert await svc.escalate_overdue() == 0


# --------------------------------------------------------------------------- #
# Approver resolution units                                                   #
# --------------------------------------------------------------------------- #
async def test_resolve_specific_user(seeded: AsyncSession) -> None:
    from app.modules.approval.models import ApprovalWorkflowStep

    svc = ApprovalService(seeded)
    emp = await _employee(seeded, "X1")
    step = ApprovalWorkflowStep(
        workflow_id=0, step_order=1, approver_type=ApproverType.SPECIFIC_USER, approver_ref="42"
    )
    assert await svc.resolve_approver(step, emp) == 42


async def test_resolve_manager_without_manager_raises(seeded: AsyncSession) -> None:
    from app.core.exceptions import ValidationError
    from app.modules.approval.models import ApprovalWorkflowStep

    svc = ApprovalService(seeded)
    emp = await _employee(seeded, "X2")  # no manager_id
    step = ApprovalWorkflowStep(workflow_id=0, step_order=1, approver_type=ApproverType.MANAGER)
    with pytest.raises(ValidationError):
        await svc.resolve_approver(step, emp)


# --------------------------------------------------------------------------- #
# API + RBAC                                                                  #
# --------------------------------------------------------------------------- #
async def test_workflow_create_requires_manage(
    seeded: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    body = {
        "target_type": "LEAVE",
        "name": "WF",
        "steps": [{"step_order": 1, "approver_type": "ROLE", "approver_ref": "HR"}],
    }
    # approval:act is not enough to configure workflows.
    forbidden = await client.post(
        f"{API}/approvals/workflows", json=body, headers=auth_header(perms=["approval:act"])
    )
    assert forbidden.status_code == 403

    ok = await client.post(
        f"{API}/approvals/workflows", json=body, headers=auth_header(perms=["approval:manage"])
    )
    assert ok.status_code == 201, ok.text
    assert len(ok.json()["data"]["steps"]) == 1


async def test_approve_via_api(
    seeded: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    await _two_step_workflow(seeded)
    org = await _org(seeded)
    instance = await _submit(seeded, org)

    # The manager (step-1 approver) approves over HTTP.
    resp = await client.post(
        f"{API}/approvals/instances/{instance.id}/approve",
        json={"comment": "OK"},
        headers=auth_header(sub=org["manager_user_id"], perms=["approval:act"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["current_step"] == 2


async def test_submit_requires_authentication(client: AsyncClient) -> None:
    resp = await client.post(
        f"{API}/approvals/leave-requests",
        json={
            "employee_id": 1,
            "leave_type": "ANNUAL",
            "start_date": "2026-05-11",
            "end_date": "2026-05-11",
        },
    )
    assert resp.status_code == 401
