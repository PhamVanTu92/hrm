"""Approval workflow use-cases.

Implements the data-defined multi-level approval engine + state machine from
docs/03b §3.3: submit -> approve/reject through ordered steps -> on final
approval publish a domain event (``LeaveApproved``) that the attendance module
consumes to compensate leave.

Concurrency: mutating actions lock the instance row (SELECT ... FOR UPDATE) so
two approvers cannot race the same step.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.recorder import record
from app.core.events import publish
from app.core.exceptions import ConflictError, NotFoundError, PermissionDenied, ValidationError
from app.core.logging import get_logger
from app.core.rbac import CurrentUser
from app.modules.approval.models import (
    ApprovalInstance,
    ApprovalStepInstance,
    ApprovalWorkflow,
    ApprovalWorkflowStep,
    ApproverType,
    InstanceStatus,
    LeaveRequest,
    LeaveStatus,
    StepAction,
    TargetType,
)
from app.modules.approval.repository import (
    InstanceRepository,
    LeaveRequestRepository,
    StepInstanceRepository,
    WorkflowRepository,
)
from app.modules.attendance.events import LeaveApproved
from app.modules.auth.models import Role, User, UserRole
from app.modules.employee.models import Employee

logger = get_logger("approval.service")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _period(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workflows = WorkflowRepository(session)
        self.instances = InstanceRepository(session)
        self.steps = StepInstanceRepository(session)
        self.leaves = LeaveRequestRepository(session)

    # ----------------------------------------------------------------- #
    # Approver resolution                                               #
    # ----------------------------------------------------------------- #
    async def _pick_user_by_role(self, role_code: str) -> int | None:
        stmt = (
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.code == role_code, User.is_active.is_(True))
            .order_by(User.id.asc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _manager_user_id(self, employee: Employee) -> int | None:
        if employee.manager_id is None:
            return None
        manager = await self.session.get(Employee, employee.manager_id)
        return manager.user_id if manager else None

    async def resolve_approver(self, step: ApprovalWorkflowStep, employee: Employee) -> int:
        """Resolve a workflow step to a concrete approver user id."""
        if step.approver_type == ApproverType.MANAGER:
            user_id = await self._manager_user_id(employee)
            if user_id is None:
                raise ValidationError("Nhân viên chưa có quản lý trực tiếp để duyệt")
            return user_id
        if step.approver_type == ApproverType.ROLE:
            user_id = await self._pick_user_by_role(step.approver_ref or "")
            if user_id is None:
                raise ValidationError(f"Không tìm thấy người duyệt cho vai trò {step.approver_ref}")
            return user_id
        if step.approver_type == ApproverType.SPECIFIC_USER:
            return int(step.approver_ref or 0)
        raise ValidationError(f"Loại người duyệt không hợp lệ: {step.approver_type}")

    # ----------------------------------------------------------------- #
    # Workflow config                                                   #
    # ----------------------------------------------------------------- #
    async def create_workflow(
        self, *, target_type: str, name: str, steps: list[dict]
    ) -> ApprovalWorkflow:
        if target_type not in TargetType.ALL:
            raise ValidationError("Loại đối tượng không hợp lệ")
        if not steps:
            raise ValidationError("Workflow cần ít nhất 1 bước")

        workflow = ApprovalWorkflow(target_type=target_type, name=name)
        for idx, step in enumerate(steps, start=1):
            approver_type = step["approver_type"]
            if approver_type not in ApproverType.ALL:
                raise ValidationError(f"Loại người duyệt không hợp lệ: {approver_type}")
            workflow.steps.append(
                ApprovalWorkflowStep(
                    step_order=step.get("step_order", idx),
                    approver_type=approver_type,
                    approver_ref=step.get("approver_ref"),
                    sla_hours=step.get("sla_hours", 24),
                )
            )
        return await self.workflows.add(workflow)

    # ----------------------------------------------------------------- #
    # Submit                                                            #
    # ----------------------------------------------------------------- #
    async def submit_leave(
        self,
        *,
        requester_id: int,
        employee_id: int,
        leave_type: str,
        start: date,
        end: date,
        is_paid: bool,
        reason: str | None,
        ip: str | None = None,
    ) -> ApprovalInstance:
        if end < start:
            raise ValidationError("Ngày kết thúc phải sau ngày bắt đầu")
        employee = await self.session.get(Employee, employee_id)
        if employee is None:
            raise NotFoundError("Không tìm thấy nhân viên")

        workflow = await self.workflows.active_for_target(TargetType.LEAVE)
        if workflow is None or not workflow.steps:
            raise ValidationError("Chưa cấu hình quy trình duyệt nghỉ phép")

        leave = LeaveRequest(
            employee_id=employee_id,
            leave_type=leave_type,
            start_date=start,
            end_date=end,
            is_paid=is_paid,
            reason=reason,
            status=LeaveStatus.PENDING,
        )
        await self.leaves.add(leave)

        instance = ApprovalInstance(
            workflow_id=workflow.id,
            target_type=TargetType.LEAVE,
            target_id=leave.id,
            requester_id=requester_id,
            employee_id=employee_id,
            current_step=1,
            status=InstanceStatus.PENDING,
            created_by=requester_id,
        )
        now = _utcnow()
        for step in workflow.steps:
            approver_user_id = await self.resolve_approver(step, employee)
            instance.steps.append(
                ApprovalStepInstance(
                    step_order=step.step_order,
                    approver_user_id=approver_user_id,
                    sla_hours=step.sla_hours,
                    # Only the first step starts its SLA clock immediately.
                    due_at=now + timedelta(hours=step.sla_hours) if step.step_order == 1 else None,
                )
            )
        await self.instances.add(instance)

        await record(
            self.session,
            actor_id=requester_id,
            action="CREATE",
            entity="approval_instances",
            entity_id=instance.id,
            new={"target_type": TargetType.LEAVE, "leave_id": leave.id},
            ip=ip,
        )
        logger.info("approval_submitted", instance_id=instance.id, employee_id=employee_id)
        return instance

    # ----------------------------------------------------------------- #
    # Approve / reject / cancel                                         #
    # ----------------------------------------------------------------- #
    async def approve(
        self, instance_id: int, actor: CurrentUser, comment: str | None, ip: str | None = None
    ) -> ApprovalInstance:
        instance = await self._load_active_locked(instance_id)
        step = await self._assert_actor_is_current_approver(instance, actor)

        step.action = StepAction.APPROVE
        step.comment = comment
        step.acted_at = _utcnow()

        last_order = max(s.step_order for s in instance.steps)
        if instance.current_step >= last_order:
            await self._finalize_approved(instance)
        else:
            await self._advance_to_next_step(instance)

        await record(
            self.session,
            actor_id=actor.id,
            action="APPROVE",
            entity="approval_instances",
            entity_id=instance.id,
            new={"step": step.step_order, "status": instance.status},
            ip=ip,
        )
        return instance

    async def reject(
        self, instance_id: int, actor: CurrentUser, comment: str | None, ip: str | None = None
    ) -> ApprovalInstance:
        instance = await self._load_active_locked(instance_id)
        step = await self._assert_actor_is_current_approver(instance, actor)

        step.action = StepAction.REJECT
        step.comment = comment
        step.acted_at = _utcnow()
        instance.status = InstanceStatus.REJECTED
        instance.completed_at = _utcnow()
        await self._set_leave_status(instance, LeaveStatus.REJECTED)
        await self.session.flush()

        await record(
            self.session,
            actor_id=actor.id,
            action="REJECT",
            entity="approval_instances",
            entity_id=instance.id,
            new={"step": step.step_order, "status": instance.status},
            ip=ip,
        )
        return instance

    async def cancel(
        self, instance_id: int, actor: CurrentUser, ip: str | None = None
    ) -> ApprovalInstance:
        instance = await self._load_active_locked(instance_id)
        if instance.requester_id != actor.id:
            raise PermissionDenied("Chỉ người tạo đơn mới được hủy")
        instance.status = InstanceStatus.CANCELLED
        instance.completed_at = _utcnow()
        await self._set_leave_status(instance, LeaveStatus.CANCELLED)
        await self.session.flush()

        await record(
            self.session,
            actor_id=actor.id,
            action="CANCEL",
            entity="approval_instances",
            entity_id=instance.id,
            ip=ip,
        )
        return instance

    # ----------------------------------------------------------------- #
    # Escalation (called by the beat task)                              #
    # ----------------------------------------------------------------- #
    async def escalate_overdue(self) -> int:
        """Reassign every overdue current step to a higher authority.

        Escalate to the approver's manager, falling back to an HR/ADMIN user.
        Returns the number of steps escalated.
        """
        now = _utcnow()
        overdue = await self.steps.overdue(now)
        escalated = 0
        for step in overdue:
            target = await self._escalation_target(step.approver_user_id)
            if target is None or target == step.approver_user_id:
                continue
            old_approver = step.approver_user_id
            step.approver_user_id = target
            step.escalated = True
            step.due_at = now + timedelta(hours=step.sla_hours)
            await record(
                self.session,
                actor_id=None,  # system action
                action="ESCALATE",
                entity="approval_step_instances",
                entity_id=step.id,
                old={"approver_user_id": old_approver},
                new={"approver_user_id": target},
            )
            escalated += 1
        await self.session.flush()
        logger.info("approval_escalations", escalated=escalated)
        return escalated

    async def _escalation_target(self, approver_user_id: int) -> int | None:
        emp = (
            await self.session.execute(select(Employee).where(Employee.user_id == approver_user_id))
        ).scalar_one_or_none()
        if emp is not None:
            manager_id = await self._manager_user_id(emp)
            if manager_id is not None:
                return manager_id
        return await self._pick_user_by_role("HR") or await self._pick_user_by_role("ADMIN")

    # ----------------------------------------------------------------- #
    # Internal state-machine helpers                                    #
    # ----------------------------------------------------------------- #
    async def _load_active_locked(self, instance_id: int) -> ApprovalInstance:
        instance = await self.instances.get_locked(instance_id)
        if instance is None:
            raise NotFoundError("Không tìm thấy đơn duyệt")
        if instance.status not in InstanceStatus.ACTIVE:
            raise ConflictError("Đơn không ở trạng thái có thể xử lý")
        return instance

    async def _assert_actor_is_current_approver(
        self, instance: ApprovalInstance, actor: CurrentUser
    ) -> ApprovalStepInstance:
        step = await self.instances.current_step(instance)
        if step is None:
            raise ConflictError("Không xác định được bước duyệt hiện tại")
        if step.approver_user_id != actor.id:
            raise PermissionDenied("Bạn không phải người duyệt ở bước này")
        if step.action is not None:
            raise ConflictError("Bước này đã được xử lý")
        return step

    async def _advance_to_next_step(self, instance: ApprovalInstance) -> None:
        instance.current_step += 1
        instance.status = InstanceStatus.IN_PROGRESS
        next_step = await self.instances.step_at(instance.id, instance.current_step)
        if next_step is not None:
            next_step.due_at = _utcnow() + timedelta(hours=next_step.sla_hours)
        await self.session.flush()

    async def _finalize_approved(self, instance: ApprovalInstance) -> None:
        instance.status = InstanceStatus.APPROVED
        instance.completed_at = _utcnow()
        leave = await self._set_leave_status(instance, LeaveStatus.APPROVED)
        await self.session.flush()
        if leave is not None:
            await publish(
                LeaveApproved(
                    session=self.session,
                    employee_id=leave.employee_id,
                    start=leave.start_date,
                    end=leave.end_date,
                    paid=leave.is_paid,
                    leave_type=leave.leave_type,
                    period=_period(leave.start_date),
                )
            )

    async def _set_leave_status(
        self, instance: ApprovalInstance, status: str
    ) -> LeaveRequest | None:
        if instance.target_type != TargetType.LEAVE:
            return None
        leave = await self.leaves.get(instance.target_id)
        if leave is not None:
            leave.status = status
        return leave
