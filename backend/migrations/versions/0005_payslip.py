"""payslip: file attachments + payslips

Revision ID: 0005_payslip
Revises: 0004_payroll
Create Date: 2026-05-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_payslip"
down_revision: str | None = "0004_payroll"
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
    op.create_table(
        "file_attachments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("entity_id", sa.BigInteger, nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column(
            "content_type",
            sa.String(100),
            nullable=False,
            server_default="application/octet-stream",
        ),
        sa.Column("encrypted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("size", sa.Integer, nullable=True),
        *_ts_columns(),
    )

    op.create_table(
        "payslips",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_item_id",
            sa.BigInteger,
            sa.ForeignKey("payroll_run_items.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "employee_id",
            sa.BigInteger,
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("file_id", sa.BigInteger, sa.ForeignKey("file_attachments.id"), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="PENDING"),
        sa.Column("email_status", sa.String(12), nullable=False, server_default="PENDING"),
        sa.Column("pwd_hint", sa.String(100), nullable=True),
        sa.Column("feedback", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_columns(),
    )
    op.create_index("ix_payslips_run_item_id", "payslips", ["run_item_id"])
    op.create_index("ix_payslips_employee_id", "payslips", ["employee_id"])
    op.create_index("ix_payslips_period", "payslips", ["period"])
    op.create_index("ix_payslips_status", "payslips", ["status"])


def downgrade() -> None:
    op.drop_table("payslips")
    op.drop_table("file_attachments")
