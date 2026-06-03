"""Payroll ORM models + domain constants.

Salary is computed by a *dynamic* engine: HR defines salary components and
formulas as data; a run freezes the formulas (``formula_snapshot``) and each
item freezes its inputs (``input_snapshot``) so an issued payslip can always be
reproduced for audit, even after formulas or base salary change later.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditMixin, Base, IntPKMixin, TimestampMixin


# --------------------------------------------------------------------------- #
# Domain constants                                                            #
# --------------------------------------------------------------------------- #
class ValueType:
    INPUT = "INPUT"  # imported per period (Excel)
    FIXED = "FIXED"  # constant default_value
    FORMULA = "FORMULA"  # expression evaluated by the engine
    ALL = frozenset({INPUT, FIXED, FORMULA})


class AssignmentScope:
    ALL = "ALL"
    DEPARTMENT = "DEPARTMENT"
    POSITION = "POSITION"
    EMPLOYEE = "EMPLOYEE"
    ALL_SCOPES = frozenset({ALL, DEPARTMENT, POSITION, EMPLOYEE})


class PeriodStatus:
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class RunStatus:
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"
    ACTIVE = frozenset({DRAFT, LOCKED})  # blocks a second run for the period


# The variable that holds an employee's net pay (engine output).
NET_VAR = "TONG_LUONG"


# --------------------------------------------------------------------------- #
# Component / formula definitions                                             #
# --------------------------------------------------------------------------- #
class SalaryComponent(Base, IntPKMixin, TimestampMixin):
    """A salary item. ``var_code`` is the identifier used inside formulas."""

    __tablename__ = "salary_components"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    var_code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    value_type: Mapped[str] = mapped_column(String(10), nullable=False)
    default_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    expression: Mapped[str | None] = mapped_column(Text, nullable=True)  # for FORMULA
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SalaryComponentAssignment(Base, IntPKMixin):
    """Scopes a component to employees over a time range."""

    __tablename__ = "salary_component_assignments"

    component_id: Mapped[int] = mapped_column(
        ForeignKey("salary_components.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[str] = mapped_column(String(12), nullable=False)
    # Department/position/employee id depending on scope (NULL for ALL).
    scope_ref: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)


# --------------------------------------------------------------------------- #
# Periods / runs / items                                                      #
# --------------------------------------------------------------------------- #
class PayrollPeriod(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "payroll_periods"

    code: Mapped[str] = mapped_column(String(7), unique=True, nullable=False)  # 'YYYY-MM'
    status: Mapped[str] = mapped_column(String(10), default=PeriodStatus.OPEN, nullable=False)
    standard_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("22.00"), nullable=False
    )


class PayrollRun(Base, IntPKMixin, TimestampMixin, AuditMixin):
    """A calculation run for a period. ``formula_snapshot`` freezes formulas at
    run creation; a partial unique index enforces one active run per period."""

    __tablename__ = "payroll_runs"
    __table_args__ = (
        Index(
            "uq_active_run_per_period",
            "period_id",
            unique=True,
            postgresql_where=text("status IN ('DRAFT', 'LOCKED')"),
        ),
    )

    period_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_periods.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(10), default=RunStatus.DRAFT, nullable=False)
    formula_snapshot: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)


class PayrollRunItem(Base, IntPKMixin):
    """Per-employee result. ``input_snapshot`` + the run's formula snapshot make
    the row reproducible; ``enc_net_amount`` stores net pay encrypted."""

    __tablename__ = "payroll_run_items"
    __table_args__ = (UniqueConstraint("run_id", "employee_id", name="uq_run_item"),)

    run_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    input_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    enc_net_amount: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="CALCULATED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PayrollInputValue(Base, IntPKMixin):
    """An imported INPUT value for (period, employee, component)."""

    __tablename__ = "payroll_input_values"
    __table_args__ = (
        UniqueConstraint("period_id", "employee_id", "component_id", name="uq_input_value"),
    )

    period_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    component_id: Mapped[int] = mapped_column(
        ForeignKey("salary_components.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


class PayrollOverride(Base, IntPKMixin):
    """Per-employee per-period context overrides (e.g. maternity:
    ``{"company_salary": 0, "bhxh_tag": true}``). Merged last into the context."""

    __tablename__ = "payroll_overrides"
    __table_args__ = (UniqueConstraint("period_id", "employee_id", name="uq_override"),)

    period_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
