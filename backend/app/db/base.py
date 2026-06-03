"""SQLAlchemy declarative base + reusable mixins.

All models inherit :class:`Base`. Mixins provide cross-cutting columns:
timestamps, soft-delete and audit attribution. Use ``BigInteger`` identity PKs
for scalability.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        # Default table name = snake_case is set explicitly per-model; this is a
        # safe fallback (lowercased class name).
        return cls.__name__.lower()


class IntPKMixin:
    """Big integer identity primary key."""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    """``created_at`` / ``updated_at`` managed by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Soft delete flag + timestamp. Repositories filter these out by default."""

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditMixin:
    """Attribution columns: who created / last updated the row."""

    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
