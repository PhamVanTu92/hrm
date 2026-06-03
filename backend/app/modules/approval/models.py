"""Approval workflow ORM models + domain constants.

The approval chain is *data-defined* (not hard-coded): a workflow has ordered
steps, each resolving to a concrete approver at submission time. An instance
walks the steps via a small state machine (see docs/03b §3.3).

LEAVE is implemented end-to-end as a concrete target (``LeaveRequest``); BENEFIT
follows the same shape and can be added without engine changes.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AuditMixin, Base, IntPKMixin, TimestampMixin


# --------------------------------------------------------------------------- #
# Domain constants                                                            #
# --------------------------------------------------------------------------- #
class TargetType:
    LEAVE = "LEAVE"
    BENEFIT = "BENEFIT"
    ALL = frozenset({LEAVE, BENEFIT})


class ApproverType:
    MANAGER = "MANAGER"  # the employee's direct manager (dynamic per request)
    ROLE = "ROLE"  # any active user holding role ``approver_ref``
    SPECIFIC_USER = "SPECIFIC_USER"  # a fixed user id in ``approver_ref``
    ALL = frozenset({MANAGER, ROLE, SPECIFIC_USER})


class InstanceStatus:
    PENDING = "PENDING"  # created, no approval yet
    IN_PROGRESS = "IN_PROGRESS"  # at least one step approved, not final
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ACTIVE = frozenset({PENDING, IN_PROGRESS})  # states that accept actions


class StepAction:
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class LeaveStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------- #
# Workflow definition (config)                                                #
# --------------------------------------------------------------------------- #
class ApprovalWorkflow(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "approval_workflows"

    target_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    steps: Mapped[list[ApprovalWorkflowStep]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="ApprovalWorkflowStep.step_order",
        lazy="selectin",
    )


class ApprovalWorkflowStep(Base, IntPKMixin):
    __tablename__ = "approval_workflow_steps"
    __table_args__ = (UniqueConstraint("workflow_id", "step_order", name="uq_workflow_step_order"),)

    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("approval_workflows.id", ondelete="CASCADE"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Role code or specific user id, depending on approver_type (NULL for MANAGER).
    approver_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sla_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)

    workflow: Mapped[ApprovalWorkflow] = relationship(back_populates="steps")


# --------------------------------------------------------------------------- #
# Running instance                                                            #
# --------------------------------------------------------------------------- #
class ApprovalInstance(Base, IntPKMixin, TimestampMixin, AuditMixin):
    __tablename__ = "approval_instances"

    workflow_id: Mapped[int] = mapped_column(ForeignKey("approval_workflows.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)  # leave_request id
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=InstanceStatus.PENDING, nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list[ApprovalStepInstance]] = relationship(
        back_populates="instance",
        cascade="all, delete-orphan",
        order_by="ApprovalStepInstance.step_order",
        lazy="selectin",
    )


class ApprovalStepInstance(Base, IntPKMixin):
    __tablename__ = "approval_step_instances"
    __table_args__ = (UniqueConstraint("instance_id", "step_order", name="uq_instance_step_order"),)

    instance_id: Mapped[int] = mapped_column(
        ForeignKey("approval_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    sla_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    # Set when the step becomes the current one (drives SLA escalation).
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action: Mapped[str | None] = mapped_column(String(8), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    instance: Mapped[ApprovalInstance] = relationship(back_populates="steps")


# --------------------------------------------------------------------------- #
# Concrete target: leave request                                              #
# --------------------------------------------------------------------------- #
class LeaveRequest(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "leave_requests"

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    leave_type: Mapped[str] = mapped_column(String(40), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=LeaveStatus.PENDING, nullable=False, index=True
    )
