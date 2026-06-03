"""Attendance ORM models + domain constants.

Pipeline (see docs/03a):

    timeclock device --pull--> raw_logs --normalize--> daily --aggregate--> monthly

Every layer uses a UNIQUE natural key + UPSERT so re-running is idempotent and
recomputation is always safe.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntPKMixin, TimestampMixin


# --------------------------------------------------------------------------- #
# Domain constants                                                            #
# --------------------------------------------------------------------------- #
class DailyStatus:
    """Status of a single attendance day."""

    NORMAL = "NORMAL"  # has punches -> work computed from shift
    MISSING = "MISSING"  # working day, no punches, no leave
    LEAVE = "LEAVE"  # covered by an approved leave request
    HOLIDAY = "HOLIDAY"  # public holiday
    ALL = frozenset({NORMAL, MISSING, LEAVE, HOLIDAY})


class AdapterType:
    """Supported time-clock integration strategies."""

    MDB = "MDB"  # MS Access .mdb via pyodbc / mdbtools
    SQLEXPRESS = "SQLEXPRESS"  # SQL Server Express via pyodbc DSN
    TCP = "TCP"  # ZKTeco-style device over TCP/IP (pyzk)
    MANUAL = "MANUAL"  # manual import / no live device
    ALL = frozenset({MDB, SQLEXPRESS, TCP, MANUAL})


# --------------------------------------------------------------------------- #
# Configuration tables                                                        #
# --------------------------------------------------------------------------- #
class AttendanceDevice(Base, IntPKMixin, TimestampMixin):
    """A physical/virtual time clock. Connection details live in ``config``
    (JSONB) so swapping a device or its protocol needs no code change."""

    __tablename__ = "attendance_devices"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(20), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Watermark for incremental pulls (only fetch punches after this instant).
    last_ingest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Shift(Base, IntPKMixin, TimestampMixin):
    """A work shift definition used to compute late/early/OT and work value."""

    __tablename__ = "shifts"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    late_grace_min: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Work value credited on a paid holiday for employees on this shift.
    holiday_value: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), default=Decimal("1.00"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Holiday(Base, IntPKMixin):
    """A public holiday. Paid holidays credit work without punches."""

    __tablename__ = "holidays"

    holiday_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


# --------------------------------------------------------------------------- #
# Pipeline tables                                                             #
# --------------------------------------------------------------------------- #
class RawPunchLog(Base, IntPKMixin):
    """Raw punch pulled from a device. Idempotent on
    (device_id, device_user_id, punch_at): re-pulling the same punch is a no-op.
    ``employee_id`` is resolved during ingest (may be NULL if unmapped)."""

    __tablename__ = "attendance_raw_logs"
    __table_args__ = (
        UniqueConstraint("device_id", "device_user_id", "punch_at", name="uq_raw_punch"),
    )

    device_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Enrollment id as reported by the device (maps to an employee).
    device_user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), nullable=True, index=True
    )
    punch_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Optional direction hint from the device (IN/OUT); often absent.
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AttendanceDaily(Base, IntPKMixin, TimestampMixin):
    """Normalised attendance for one employee on one day. UPSERT on
    (employee_id, work_date) so re-normalisation overwrites cleanly."""

    __tablename__ = "attendance_daily"
    __table_args__ = (UniqueConstraint("employee_id", "work_date", name="uq_daily_emp_date"),)

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"), nullable=True)
    first_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    early_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ot_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    work_value: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), default=Decimal("0.00"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(12), default=DailyStatus.MISSING, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AttendanceMonthly(Base, IntPKMixin, TimestampMixin):
    """Monthly aggregate per employee. ``locked`` is set once payroll finalises
    the period; locked rows are never overwritten by re-aggregation."""

    __tablename__ = "attendance_monthly"
    __table_args__ = (UniqueConstraint("employee_id", "period", name="uq_monthly_emp_period"),)

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # 'YYYY-MM'
    standard_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    actual_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    leave_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    paid_leave_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    ot_hours: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), default=Decimal("0.00"), nullable=False
    )
    late_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
