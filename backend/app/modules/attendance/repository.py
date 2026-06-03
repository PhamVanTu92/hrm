"""Data-access for the attendance module."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.repository import BaseRepository
from app.modules.attendance.models import (
    AttendanceDaily,
    AttendanceDevice,
    AttendanceMonthly,
    Holiday,
    RawPunchLog,
    Shift,
)


class DeviceRepository(BaseRepository[AttendanceDevice]):
    model = AttendanceDevice

    async def active_devices(self) -> list[AttendanceDevice]:
        stmt = select(AttendanceDevice).where(AttendanceDevice.is_active.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_code(self, code: str) -> AttendanceDevice | None:
        return await self.get_or_none_by(code=code)


class ShiftRepository(BaseRepository[Shift]):
    model = Shift

    async def get_by_code(self, code: str) -> Shift | None:
        return await self.get_or_none_by(code=code)

    async def default_active(self) -> Shift | None:
        """The first active shift — used when an employee has no explicit shift."""
        stmt = select(Shift).where(Shift.is_active.is_(True)).order_by(Shift.id.asc()).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()


class HolidayRepository(BaseRepository[Holiday]):
    model = Holiday

    async def get_on(self, day: date) -> Holiday | None:
        return await self.get_or_none_by(holiday_date=day)


class RawPunchRepository(BaseRepository[RawPunchLog]):
    model = RawPunchLog

    async def bulk_upsert(self, rows: list[dict]) -> int:
        """Insert raw punches, ignoring duplicates (idempotent re-pull).

        Returns the number of newly inserted rows.
        """
        if not rows:
            return 0
        stmt = (
            pg_insert(RawPunchLog)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_raw_punch")
            .returning(RawPunchLog.id)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return len(result.fetchall())

    async def punches_for(self, employee_id: int, work_date: date) -> list[RawPunchLog]:
        """All punches for an employee on a given calendar day, time-ordered."""
        stmt = (
            select(RawPunchLog)
            .where(
                RawPunchLog.employee_id == employee_id,
                func.date(RawPunchLog.punch_at) == work_date,
            )
            .order_by(RawPunchLog.punch_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def employees_punched_on(self, device_id: int, work_date: date) -> list[int]:
        """Distinct resolved employee ids that punched on this device that day."""
        stmt = (
            select(RawPunchLog.employee_id)
            .where(
                RawPunchLog.device_id == device_id,
                func.date(RawPunchLog.punch_at) == work_date,
                RawPunchLog.employee_id.is_not(None),
            )
            .distinct()
        )
        return [row[0] for row in (await self.session.execute(stmt)).all()]


class DailyRepository(BaseRepository[AttendanceDaily]):
    model = AttendanceDaily

    async def get_for(self, employee_id: int, work_date: date) -> AttendanceDaily | None:
        return await self.get_or_none_by(employee_id=employee_id, work_date=work_date)

    async def list_range(
        self, employee_id: int, date_from: date, date_to: date
    ) -> list[AttendanceDaily]:
        stmt = (
            select(AttendanceDaily)
            .where(
                AttendanceDaily.employee_id == employee_id,
                AttendanceDaily.work_date >= date_from,
                AttendanceDaily.work_date <= date_to,
            )
            .order_by(AttendanceDaily.work_date.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())


class MonthlyRepository(BaseRepository[AttendanceMonthly]):
    model = AttendanceMonthly

    async def get_for(self, employee_id: int, period: str) -> AttendanceMonthly | None:
        return await self.get_or_none_by(employee_id=employee_id, period=period)
