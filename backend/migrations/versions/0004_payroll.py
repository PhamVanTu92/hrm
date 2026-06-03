"""payroll: components, assignments, periods, runs, items, inputs, overrides

Revision ID: 0004_payroll
Revises: 0003_approval
Create Date: 2026-05-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0004_payroll"
down_revision: str | None = "0003_approval"
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
    # ---- Components + assignments ----
    op.create_table(
        "salary_components",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("var_code", sa.String(60), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("value_type", sa.String(10), nullable=False),
        sa.Column("default_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("expression", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts_columns(),
    )
    op.create_table(
        "salary_component_assignments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "component_id",
            sa.BigInteger,
            sa.ForeignKey("salary_components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(12), nullable=False),
        sa.Column("scope_ref", sa.BigInteger, nullable=True),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True),
    )
    op.create_index("ix_assignments_component_id", "salary_component_assignments", ["component_id"])

    # ---- Periods ----
    op.create_table(
        "payroll_periods",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(7), nullable=False, unique=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
        sa.Column("standard_days", sa.Numeric(5, 2), nullable=False, server_default="22.00"),
        *_ts_columns(),
    )

    # ---- Runs (one active run per period via partial unique index) ----
    op.create_table(
        "payroll_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("period_id", sa.BigInteger, sa.ForeignKey("payroll_periods.id"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="DRAFT"),
        sa.Column("formula_snapshot", pg.JSONB, nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_by", sa.BigInteger, nullable=True),
        sa.Column("updated_by", sa.BigInteger, nullable=True),
        *_ts_columns(),
    )
    op.create_index("ix_runs_period_id", "payroll_runs", ["period_id"])
    op.create_index(
        "uq_active_run_per_period",
        "payroll_runs",
        ["period_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('DRAFT', 'LOCKED')"),
    )

    # ---- Run items ----
    op.create_table(
        "payroll_run_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.BigInteger,
            sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("employee_id", sa.BigInteger, sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("input_snapshot", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("result", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("enc_net_amount", sa.LargeBinary, nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="CALCULATED"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("run_id", "employee_id", name="uq_run_item"),
    )
    op.create_index("ix_run_items_run_id", "payroll_run_items", ["run_id"])
    op.create_index("ix_run_items_employee_id", "payroll_run_items", ["employee_id"])

    # ---- Input values ----
    op.create_table(
        "payroll_input_values",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "period_id",
            sa.BigInteger,
            sa.ForeignKey("payroll_periods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.BigInteger,
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "component_id",
            sa.BigInteger,
            sa.ForeignKey("salary_components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(18, 2), nullable=False),
        sa.UniqueConstraint("period_id", "employee_id", "component_id", name="uq_input_value"),
    )
    op.create_index("ix_input_values_period_id", "payroll_input_values", ["period_id"])

    # ---- Overrides ----
    op.create_table(
        "payroll_overrides",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "period_id",
            sa.BigInteger,
            sa.ForeignKey("payroll_periods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "employee_id",
            sa.BigInteger,
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("data", pg.JSONB, nullable=False, server_default="{}"),
        sa.UniqueConstraint("period_id", "employee_id", name="uq_override"),
    )
    op.create_index("ix_overrides_period_id", "payroll_overrides", ["period_id"])


def downgrade() -> None:
    op.drop_table("payroll_overrides")
    op.drop_table("payroll_input_values")
    op.drop_table("payroll_run_items")
    op.drop_table("payroll_runs")
    op.drop_table("payroll_periods")
    op.drop_table("salary_component_assignments")
    op.drop_table("salary_components")
