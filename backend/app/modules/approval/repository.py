"""Data-access for the approval module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.db.repository import BaseRepository
from app.modules.approval.models import (
    ApprovalInstance,
    ApprovalStepInstance,
    ApprovalWorkflow,
    InstanceStatus,
    LeaveRequest,
)


class WorkflowRepository(BaseRepository[ApprovalWorkflow]):
    model = ApprovalWorkflow

    async def active_for_target(self, target_type: str) -> ApprovalWorkflow | None:
        """First active workflow for a target type (steps eager-loaded)."""
        stmt = (
            select(ApprovalWorkflow)
            .where(
                ApprovalWorkflow.target_type == target_type,
                ApprovalWorkflow.is_active.is_(True),
            )
            .order_by(ApprovalWorkflow.id.asc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class InstanceRepository(BaseRepository[ApprovalInstance]):
    model = ApprovalInstance

    async def get_locked(self, instance_id: int) -> ApprovalInstance | None:
        """Fetch an instance with a row lock (SELECT ... FOR UPDATE).

        Serialises concurrent approve/reject/cancel on the same instance.
        """
        stmt = select(ApprovalInstance).where(ApprovalInstance.id == instance_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def current_step(self, instance: ApprovalInstance) -> ApprovalStepInstance | None:
        stmt = select(ApprovalStepInstance).where(
            ApprovalStepInstance.instance_id == instance.id,
            ApprovalStepInstance.step_order == instance.current_step,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def step_at(self, instance_id: int, step_order: int) -> ApprovalStepInstance | None:
        stmt = select(ApprovalStepInstance).where(
            ApprovalStepInstance.instance_id == instance_id,
            ApprovalStepInstance.step_order == step_order,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def pending_for_approver(self, user_id: int) -> list[ApprovalInstance]:
        """Active instances whose CURRENT step is assigned to this user."""
        stmt = (
            select(ApprovalInstance)
            .join(
                ApprovalStepInstance,
                ApprovalStepInstance.instance_id == ApprovalInstance.id,
            )
            .where(
                ApprovalInstance.status.in_(tuple(InstanceStatus.ACTIVE)),
                ApprovalStepInstance.step_order == ApprovalInstance.current_step,
                ApprovalStepInstance.approver_user_id == user_id,
                ApprovalStepInstance.action.is_(None),
            )
            .order_by(ApprovalInstance.id.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())


class StepInstanceRepository(BaseRepository[ApprovalStepInstance]):
    model = ApprovalStepInstance

    async def overdue(self, now: datetime) -> list[ApprovalStepInstance]:
        """Current, un-acted steps whose SLA deadline has passed."""
        stmt = (
            select(ApprovalStepInstance)
            .join(
                ApprovalInstance,
                ApprovalInstance.id == ApprovalStepInstance.instance_id,
            )
            .where(
                ApprovalInstance.status.in_(tuple(InstanceStatus.ACTIVE)),
                ApprovalStepInstance.step_order == ApprovalInstance.current_step,
                ApprovalStepInstance.action.is_(None),
                ApprovalStepInstance.due_at.is_not(None),
                ApprovalStepInstance.due_at < now,
            )
        )
        return list((await self.session.execute(stmt)).scalars().all())


class LeaveRequestRepository(BaseRepository[LeaveRequest]):
    model = LeaveRequest
