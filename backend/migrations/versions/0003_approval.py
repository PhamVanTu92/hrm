"""approval: workflows, steps, instances, step instances, leave requests

Revision ID: 0003_approval
Revises: 0002_attendance
Create Date: 2026-05-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_approval"
down_revision: str | None = "0002_attendance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    # ---- Workflow definition ----
    op.create_table(
        "approval_workflows",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts_columns(),
    )
    op.create_index("ix_workflows_target_type", "approval_workflows", ["target_type"])

    op.create_table(
        "approval_workflow_steps",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_id",
            sa.BigInteger,
            sa.ForeignKey("approval_workflows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("approver_type", sa.String(20), nullable=False),
        sa.Column("approver_ref", sa.String(50), nullable=True),
        sa.Column("sla_hours", sa.Integer, nullable=False, server_default="24"),
        sa.UniqueConstraint("workflow_id", "step_order", name="uq_workflow_step_order"),
    )

    # ---- Leave requests (concrete target) ----
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "employee_id",
            sa.BigInteger,
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("leave_type", sa.String(40), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("is_paid", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        *_ts_columns(),
    )
    op.create_index("ix_leave_employee_id", "leave_requests", ["employee_id"])
    op.create_index("ix_leave_status", "leave_requests", ["status"])

    # ---- Running instances ----
    op.create_table(
        "approval_instances",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_id", sa.BigInteger, sa.ForeignKey("approval_workflows.id"), nullable=False
        ),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.Integer, nullable=False),
        sa.Column("requester_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("employee_id", sa.BigInteger, sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("current_step", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger, nullable=True),
        sa.Column("updated_by", sa.BigInteger, nullable=True),
        *_ts_columns(),
    )
    op.create_index("ix_instances_status", "approval_instances", ["status"])

    op.create_table(
        "approval_step_instances",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "instance_id",
            sa.BigInteger,
            sa.ForeignKey("approval_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_order", sa.Integer, nullable=False),
        sa.Column("approver_user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sla_hours", sa.Integer, nullable=False, server_default="24"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action", sa.String(8), nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("instance_id", "step_order", name="uq_instance_step_order"),
    )
    op.create_index("ix_step_instances_instance_id", "approval_step_instances", ["instance_id"])
    op.create_index("ix_step_instances_approver", "approval_step_instances", ["approver_user_id"])


def downgrade() -> None:
    op.drop_table("approval_step_instances")
    op.drop_table("approval_instances")
    op.drop_table("leave_requests")
    op.drop_table("approval_workflow_steps")
    op.drop_table("approval_workflows")
