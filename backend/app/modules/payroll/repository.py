"""Data-access for the payroll module."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.repository import BaseRepository
from app.modules.payroll.models import (
    AssignmentScope,
    PayrollInputValue,
    PayrollOverride,
    PayrollPeriod,
    PayrollRun,
    PayrollRunItem,
    RunStatus,
    SalaryComponent,
    SalaryComponentAssignment,
    ValueType,
)


class ComponentRepository(BaseRepository[SalaryComponent]):
    model = SalaryComponent

    async def get_by_code(self, code: str) -> SalaryComponent | None:
        return await self.get_or_none_by(code=code)

    async def get_by_var_code(self, var_code: str) -> SalaryComponent | None:
        return await self.get_or_none_by(var_code=var_code)

    async def active(self) -> list[SalaryComponent]:
        stmt = select(SalaryComponent).where(SalaryComponent.is_active.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    async def active_formulas(self) -> list[SalaryComponent]:
        stmt = select(SalaryComponent).where(
            SalaryComponent.is_active.is_(True),
            SalaryComponent.value_type == ValueType.FORMULA,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_employee(
        self,
        *,
        department_id: int | None,
        position_id: int | None,
        employee_id: int,
        start: date,
        end: date,
    ) -> list[SalaryComponent]:
        """Active components assigned to an employee, effective within a period.

        Resolves the assignment scope (ALL / DEPARTMENT / POSITION / EMPLOYEE).
        """
        scope_match = [SalaryComponentAssignment.scope == AssignmentScope.ALL]
        if department_id is not None:
            scope_match.append(
                and_(
                    SalaryComponentAssignment.scope == AssignmentScope.DEPARTMENT,
                    SalaryComponentAssignment.scope_ref == department_id,
                )
            )
        if position_id is not None:
            scope_match.append(
                and_(
                    SalaryComponentAssignment.scope == AssignmentScope.POSITION,
                    SalaryComponentAssignment.scope_ref == position_id,
                )
            )
        scope_match.append(
            and_(
                SalaryComponentAssignment.scope == AssignmentScope.EMPLOYEE,
                SalaryComponentAssignment.scope_ref == employee_id,
            )
        )

        stmt = (
            select(SalaryComponent)
            .join(
                SalaryComponentAssignment,
                SalaryComponentAssignment.component_id == SalaryComponent.id,
            )
            .where(
                SalaryComponent.is_active.is_(True),
                or_(*scope_match),
                SalaryComponentAssignment.effective_from <= end,
                or_(
                    SalaryComponentAssignment.effective_to.is_(None),
                    SalaryComponentAssignment.effective_to >= start,
                ),
            )
            .distinct()
        )
        return list((await self.session.execute(stmt)).scalars().all())


class AssignmentRepository(BaseRepository[SalaryComponentAssignment]):
    model = SalaryComponentAssignment


class PeriodRepository(BaseRepository[PayrollPeriod]):
    model = PayrollPeriod

    async def get_by_code(self, code: str) -> PayrollPeriod | None:
        return await self.get_or_none_by(code=code)


class RunRepository(BaseRepository[PayrollRun]):
    model = PayrollRun

    async def active_for_period(self, period_id: int) -> PayrollRun | None:
        stmt = select(PayrollRun).where(
            PayrollRun.period_id == period_id,
            PayrollRun.status.in_(tuple(RunStatus.ACTIVE)),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_locked(self, run_id: int) -> PayrollRun | None:
        stmt = select(PayrollRun).where(PayrollRun.id == run_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()


class RunItemRepository(BaseRepository[PayrollRunItem]):
    model = PayrollRunItem

    async def delete_for_run(self, run_id: int) -> None:
        await self.session.execute(delete(PayrollRunItem).where(PayrollRunItem.run_id == run_id))
        await self.session.flush()

    async def delete_for_employees(self, run_id: int, employee_ids: list[int]) -> None:
        """Delete only the given employees' items (chunked recompute path)."""
        if not employee_ids:
            return
        await self.session.execute(
            delete(PayrollRunItem).where(
                PayrollRunItem.run_id == run_id,
                PayrollRunItem.employee_id.in_(employee_ids),
            )
        )
        await self.session.flush()

    async def get_for(self, run_id: int, employee_id: int) -> PayrollRunItem | None:
        return await self.get_or_none_by(run_id=run_id, employee_id=employee_id)

    async def list_for_run(self, run_id: int) -> list[PayrollRunItem]:
        stmt = select(PayrollRunItem).where(PayrollRunItem.run_id == run_id)
        return list((await self.session.execute(stmt)).scalars().all())


class InputValueRepository(BaseRepository[PayrollInputValue]):
    model = PayrollInputValue

    async def map_for(self, period_id: int, employee_id: int) -> dict[int, Decimal]:
        """Return {component_id: value} for an employee in a period."""
        stmt = select(PayrollInputValue.component_id, PayrollInputValue.value).where(
            PayrollInputValue.period_id == period_id,
            PayrollInputValue.employee_id == employee_id,
        )
        return {cid: val for cid, val in (await self.session.execute(stmt)).all()}

    async def upsert(
        self, *, period_id: int, employee_id: int, component_id: int, value: Decimal
    ) -> None:
        stmt = (
            pg_insert(PayrollInputValue)
            .values(
                period_id=period_id,
                employee_id=employee_id,
                component_id=component_id,
                value=value,
            )
            .on_conflict_do_update(constraint="uq_input_value", set_={"value": value})
        )
        await self.session.execute(stmt)
        await self.session.flush()


class OverrideRepository(BaseRepository[PayrollOverride]):
    model = PayrollOverride

    async def get_for(self, period_id: int, employee_id: int) -> PayrollOverride | None:
        return await self.get_or_none_by(period_id=period_id, employee_id=employee_id)
