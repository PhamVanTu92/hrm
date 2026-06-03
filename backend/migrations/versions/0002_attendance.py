"""attendance: devices, shifts, holidays, raw logs, daily, monthly

Revision ID: 0002_attendance
Revises: 0001_initial
Create Date: 2026-05-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0002_attendance"
down_revision: str | None = "0001_initial"
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
    # ---- Devices ----
    op.create_table(
        "attendance_devices",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("adapter_type", sa.String(20), nullable=False),
        sa.Column("config", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_ingest_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_columns(),
    )

    # ---- Shifts ----
    op.create_table(
        "shifts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
        sa.Column("break_minutes", sa.Integer, nullable=False, server_default="60"),
        sa.Column("late_grace_min", sa.Integer, nullable=False, server_default="0"),
        sa.Column("holiday_value", sa.Numeric(4, 2), nullable=False, server_default="1.00"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *_ts_columns(),
    )

    # ---- Holidays ----
    op.create_table(
        "holidays",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("holiday_date", sa.Date, nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("is_paid", sa.Boolean, nullable=False, server_default=sa.true()),
    )

    # ---- Raw punch logs (idempotent on device+user+timestamp) ----
    op.create_table(
        "attendance_raw_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "device_id",
            sa.BigInteger,
            sa.ForeignKey("attendance_devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_user_id", sa.String(50), nullable=False),
        sa.Column("employee_id", sa.BigInteger, sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("punch_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.String(8), nullable=True),
        sa.Column("raw", pg.JSONB, nullable=True),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("device_id", "device_user_id", "punch_at", name="uq_raw_punch"),
    )
    op.create_index("ix_raw_logs_device_id", "attendance_raw_logs", ["device_id"])
    op.create_index("ix_raw_logs_employee_id", "attendance_raw_logs", ["employee_id"])

    # ---- Daily (UPSERT on employee+date) ----
    op.create_table(
        "attendance_daily",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "employee_id",
            sa.BigInteger,
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("work_date", sa.Date, nullable=False),
        sa.Column("shift_id", sa.BigInteger, sa.ForeignKey("shifts.id"), nullable=True),
        sa.Column("first_in", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_out", sa.DateTime(timezone=True), nullable=True),
        sa.Column("late_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("early_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ot_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("work_value", sa.Numeric(4, 2), nullable=False, server_default="0.00"),
        sa.Column("status", sa.String(12), nullable=False, server_default="MISSING"),
        sa.Column("note", sa.String(255), nullable=True),
        *_ts_columns(),
        sa.UniqueConstraint("employee_id", "work_date", name="uq_daily_emp_date"),
    )
    op.create_index("ix_daily_employee_id", "attendance_daily", ["employee_id"])
    op.create_index("ix_daily_work_date", "attendance_daily", ["work_date"])

    # ---- Monthly (UPSERT on employee+period, lock-guarded) ----
    op.create_table(
        "attendance_monthly",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "employee_id",
            sa.BigInteger,
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("standard_days", sa.Numeric(5, 2), nullable=False, server_default="0.00"),
        sa.Column("actual_days", sa.Numeric(5, 2), nullable=False, server_default="0.00"),
        sa.Column("leave_days", sa.Numeric(5, 2), nullable=False, server_default="0.00"),
        sa.Column("paid_leave_days", sa.Numeric(5, 2), nullable=False, server_default="0.00"),
        sa.Column("ot_hours", sa.Numeric(6, 2), nullable=False, server_default="0.00"),
        sa.Column("late_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked", sa.Boolean, nullable=False, server_default=sa.false()),
        *_ts_columns(),
        sa.UniqueConstraint("employee_id", "period", name="uq_monthly_emp_period"),
    )
    op.create_index("ix_monthly_employee_id", "attendance_monthly", ["employee_id"])
    op.create_index("ix_monthly_period", "attendance_monthly", ["period"])


def downgrade() -> None:
    op.drop_table("attendance_monthly")
    op.drop_table("attendance_daily")
    op.drop_table("attendance_raw_logs")
    op.drop_table("holidays")
    op.drop_table("shifts")
    op.drop_table("attendance_devices")
