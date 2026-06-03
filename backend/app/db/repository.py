"""Generic async base repository.

Provides typed CRUD building blocks reused by every module repository. Keeps SQL
concerns out of services. Soft-deleted rows are excluded by default.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageParams
from app.db.base import Base, SoftDeleteMixin

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Generic repository over a single ORM model."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- internal helpers ----

    def _base_select(self) -> Select[tuple[ModelT]]:
        stmt = select(self.model)
        if issubclass(self.model, SoftDeleteMixin):
            stmt = stmt.where(self.model.is_deleted.is_(False))
        return stmt

    def _apply_sort(self, stmt: Select[Any], params: PageParams) -> Select[Any]:
        for field_name, is_desc in params.parse_sort():
            column = getattr(self.model, field_name, None)
            if column is None:
                continue
            stmt = stmt.order_by(column.desc() if is_desc else column.asc())
        return stmt

    # ---- reads ----

    async def get(self, id_: int) -> ModelT | None:
        """Fetch by primary key (excludes soft-deleted)."""
        stmt = self._base_select().where(self.model.id == id_)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_none_by(self, **filters: Any) -> ModelT | None:
        """Fetch a single row matching equality filters, or ``None``."""
        stmt = self._base_select()
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_page(
        self,
        params: PageParams,
        *,
        filters: list[Any] | None = None,
    ) -> tuple[list[ModelT], int]:
        """Return a page of rows + total count for the given filters.

        Args:
            params: pagination/sort params.
            filters: list of SQLAlchemy boolean expressions (already built by
                the caller for full control over filtering).
        """
        stmt = self._base_select()
        if filters:
            for clause in filters:
                stmt = stmt.where(clause)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = self._apply_sort(stmt, params).offset(params.offset).limit(params.size)
        rows = list((await self.session.execute(stmt)).scalars().all())
        return rows, total

    # ---- writes ----

    async def add(self, instance: ModelT) -> ModelT:
        """Persist a new instance (flush to populate PK, no commit)."""
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, instance: ModelT, *, hard: bool = False) -> None:
        """Soft-delete by default; hard-delete only when explicitly requested."""
        if not hard and isinstance(instance, SoftDeleteMixin):
            from datetime import datetime

            instance.is_deleted = True
            instance.deleted_at = datetime.now(UTC)
            await self.session.flush()
        else:
            await self.session.delete(instance)
            await self.session.flush()
