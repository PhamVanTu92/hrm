"""Payslip + file attachment ORM models.

Flow (docs/03c §3.5): payroll run locked -> a Payslip row per run item
(PENDING) -> employee confirms -> a Celery chain renders the PDF, encrypts it
with the employee's CCCD, uploads to object storage (recorded as a
``FileAttachment``) and emails it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IntPKMixin, TimestampMixin


class FileKind:
    PAYSLIP = "PAYSLIP"


class PayslipStatus:
    PENDING = "PENDING"  # awaiting employee confirmation
    CONFIRMED = "CONFIRMED"  # employee confirmed -> PDF pipeline runs
    REJECTED = "REJECTED"  # employee disputes the figures
    ACTIVE = frozenset({PENDING, CONFIRMED, REJECTED})


class EmailStatus:
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class FileAttachment(Base, IntPKMixin, TimestampMixin):
    """A stored object (S3/MinIO key) attached to some entity."""

    __tablename__ = "file_attachments"

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Payslip(Base, IntPKMixin, TimestampMixin):
    __tablename__ = "payslips"

    run_item_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_run_items.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("file_attachments.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        String(12), default=PayslipStatus.PENDING, nullable=False, index=True
    )
    email_status: Mapped[str] = mapped_column(
        String(12), default=EmailStatus.PENDING, nullable=False
    )
    pwd_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
