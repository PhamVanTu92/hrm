"""Data-access for the employee module."""

from __future__ import annotations

from sqlalchemy import select

from app.db.repository import BaseRepository
from app.modules.employee.models import (
    Employee,
    EmployeeDynamicProfile,
    ProfileField,
)
from app.modules.employee.schemas import EmployeeFilter


class EmployeeRepository(BaseRepository[Employee]):
    model = Employee

    def build_filters(self, f: EmployeeFilter) -> list:
        """Translate the filter schema into SQLAlchemy clauses."""
        clauses: list = []
        if f.department_id is not None:
            clauses.append(Employee.department_id == f.department_id)
        if f.position_id is not None:
            clauses.append(Employee.position_id == f.position_id)
        if f.status is not None:
            clauses.append(Employee.status == f.status)
        if f.q:
            # pg_trgm-backed ILIKE search on full_name.
            clauses.append(Employee.full_name.ilike(f"%{f.q}%"))
        return clauses

    async def get_by_code(self, code: str) -> Employee | None:
        return await self.get_or_none_by(employee_code=code)

    async def find_by_national_id_index(self, bidx: str) -> Employee | None:
        stmt = select(Employee).where(
            Employee.national_id_bidx == bidx, Employee.is_deleted.is_(False)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class DynamicProfileRepository(BaseRepository[EmployeeDynamicProfile]):
    model = EmployeeDynamicProfile

    async def get_for_employee(self, employee_id: int) -> EmployeeDynamicProfile | None:
        stmt = select(EmployeeDynamicProfile).where(
            EmployeeDynamicProfile.employee_id == employee_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class ProfileFieldRepository(BaseRepository[ProfileField]):
    model = ProfileField

    async def active_fields(self) -> list[ProfileField]:
        stmt = select(ProfileField).where(ProfileField.is_active.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())
