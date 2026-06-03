"""Employee, organisation and dynamic-profile ORM models.

Sensitive columns are stored AES-256 encrypted as ``BYTEA`` (``enc_*``). The
dynamic profile stores arbitrary HR-defined fields in a JSONB column; encrypted
fields are stored as ``enc:<base64>`` strings inside that JSON.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import AuditMixin, Base, IntPKMixin, SoftDeleteMixin, TimestampMixin


class Department(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "departments"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    manager_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Position(Base, IntPKMixin):
    __tablename__ = "positions"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)


class Employee(Base, IntPKMixin, TimestampMixin, SoftDeleteMixin, AuditMixin):
    __tablename__ = "employees"

    employee_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id"), nullable=True, index=True
    )
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), nullable=True, index=True
    )
    join_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)

    # ---- Encrypted sensitive fields (AES-256-GCM, BYTEA) ----
    enc_national_id: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    enc_phone: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    enc_bank_account: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    enc_base_salary: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Blind index for exact-match search on national id without exposing it.
    national_id_bidx: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    profile: Mapped[EmployeeDynamicProfile | None] = relationship(
        back_populates="employee", uselist=False, cascade="all, delete-orphan"
    )


class ProfileCategory(Base, IntPKMixin):
    __tablename__ = "profile_categories"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ProfileField(Base, IntPKMixin):
    __tablename__ = "profile_fields"
    __table_args__ = (UniqueConstraint("category_id", "field_key", name="uq_field_key"),)

    category_id: Mapped[int] = mapped_column(ForeignKey("profile_categories.id"), nullable=False)
    field_key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    # TEXT / NUMBER / DATE / SELECT / BOOLEAN
    data_type: Mapped[str] = mapped_column(String(20), nullable=False)
    options: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class EmployeeDynamicProfile(Base):
    __tablename__ = "employee_dynamic_profiles"

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    employee: Mapped[Employee] = relationship(back_populates="profile")
