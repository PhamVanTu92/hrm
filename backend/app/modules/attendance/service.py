"""Attendance use-cases: ingest -> normalise -> aggregate, plus leave
compensation and audited manual adjustments.

The normalisation/aggregation logic implements docs/03a §3.2. Every step is
idempotent (UNIQUE natural keys + recompute-safe upserts).
"""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.recorder import record
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.rbac import CurrentUser
from app.modules.attendance.adapters.base import RawPunch
from app.modules.attendance.models import (
    AttendanceDaily,
    AttendanceDevice,
    DailyStatus,
    Holiday,
    Shift,
)
from app.modules.attendance.repository import (
    DailyRepository,
    DeviceRepository,
    HolidayRepository,
    MonthlyRepository,
    RawPunchRepository,
    ShiftRepository,
)
from app.modules.employee.models import Employee

logger = get_logger("attendance.service")

_ZERO = Decimal("0.00")
_FULL = Decimal("1.00")


def _minutes_of_day(t: time) -> int:
    """Minutes since midnight for a time-of-day."""
    return t.hour * 60 + t.minute


def _round_to_half(ratio: float) -> Decimal:
    """Round a worked/required ratio to the nearest 0.5, clamped to [0, 1]."""
    half_steps = round(ratio * 2)
    value = Decimal(half_steps) / Decimal(2)
    return min(max(value, _ZERO), _FULL)


class AttendanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.devices = DeviceRepository(session)
        self.shifts = ShiftRepository(session)
        self.holidays = HolidayRepository(session)
        self.raw = RawPunchRepository(session)
        self.daily = DailyRepository(session)
        self.monthly = MonthlyRepository(session)

    # ----------------------------------------------------------------- #
    # Ingest                                                            #
    # ----------------------------------------------------------------- #
    async def ingest_punches(self, device_id: int, punches: list[RawPunch]) -> int:
        """Resolve device user ids -> employees and upsert raw punches.

        ``device_user_id`` is matched to ``Employee.employee_code`` (the default
        mapping; replace with a dedicated enrolment table if they diverge).
        Returns the count of newly inserted punches.
        """
        if not punches:
            return 0
        codes = {p.device_user_id for p in punches}
        rows_map = (
            await self.session.execute(
                select(Employee.employee_code, Employee.id).where(Employee.employee_code.in_(codes))
            )
        ).all()
        code_to_id = {code: emp_id for code, emp_id in rows_map}

        rows = [
            {
                "device_id": device_id,
                "device_user_id": p.device_user_id,
                "employee_id": code_to_id.get(p.device_user_id),
                "punch_at": p.punch_at,
                "direction": p.direction,
                "raw": p.raw or None,
            }
            for p in punches
        ]
        inserted = await self.raw.bulk_upsert(rows)
        logger.info("attendance_ingest", device_id=device_id, received=len(rows), inserted=inserted)
        return inserted

    # ----------------------------------------------------------------- #
    # Normalise                                                         #
    # ----------------------------------------------------------------- #
    async def normalize_device_day(self, device_id: int, work_date: date) -> int:
        """Normalise every employee that punched on a device for a given day."""
        employee_ids = await self.raw.employees_punched_on(device_id, work_date)
        shift = await self.shifts.default_active()
        for employee_id in employee_ids:
            await self.normalize_day(employee_id, work_date, shift=shift)
        return len(employee_ids)

    async def normalize_day(
        self, employee_id: int, work_date: date, *, shift: Shift | None = None
    ) -> AttendanceDaily:
        """Compute a single :class:`AttendanceDaily` from raw punches + shift.

        Implements the late/early/OT/work-value rules from the design. Safe to
        re-run: it overwrites the existing row for (employee, date).
        """
        if shift is None:
            shift = await self.shifts.default_active()

        punches = await self.raw.punches_for(employee_id, work_date)
        daily = await self.daily.get_for(employee_id, work_date)
        if daily is None:
            daily = AttendanceDaily(employee_id=employee_id, work_date=work_date)
        daily.shift_id = shift.id if shift else None

        if not punches:
            return await self._normalize_empty_day(daily, employee_id, work_date, shift)

        return await self._normalize_punched_day(daily, punches, shift)

    async def _normalize_empty_day(
        self,
        daily: AttendanceDaily,
        employee_id: int,
        work_date: date,
        shift: Shift | None,
    ) -> AttendanceDaily:
        # Preserve a leave already applied by the approval flow.
        if daily.status == DailyStatus.LEAVE:
            return await self._save_daily(daily)

        holiday = await self.holidays.get_on(work_date)
        daily.first_in = daily.last_out = None
        daily.late_minutes = daily.early_minutes = daily.ot_minutes = 0
        if holiday and holiday.is_paid:
            daily.status = DailyStatus.HOLIDAY
            daily.work_value = shift.holiday_value if shift else _FULL
        else:
            daily.status = DailyStatus.MISSING
            daily.work_value = _ZERO
        return await self._save_daily(daily)

    async def _normalize_punched_day(
        self, daily: AttendanceDaily, punches: list, shift: Shift | None
    ) -> AttendanceDaily:
        first_in = punches[0].punch_at
        last_out = punches[-1].punch_at
        daily.first_in = first_in
        daily.last_out = last_out
        daily.status = DailyStatus.NORMAL

        if shift is None:
            # No shift configured -> credit a full day, no late/early/OT.
            daily.late_minutes = daily.early_minutes = daily.ot_minutes = 0
            daily.work_value = _FULL
            return await self._save_daily(daily)

        in_min = _minutes_of_day(first_in.time())
        out_min = _minutes_of_day(last_out.time())
        start_min = _minutes_of_day(shift.start_time)
        end_min = _minutes_of_day(shift.end_time)

        daily.late_minutes = max(0, in_min - start_min - shift.late_grace_min)
        daily.early_minutes = max(0, end_min - out_min)
        # Gross overtime past shift end; only credited in payroll if an OT
        # request was approved (enforced downstream, not here).
        daily.ot_minutes = max(0, out_min - end_min)

        worked = (out_min - in_min) - shift.break_minutes
        required = (end_min - start_min) - shift.break_minutes
        ratio = worked / required if required > 0 else 0.0
        daily.work_value = _round_to_half(ratio)
        return await self._save_daily(daily)

    async def _save_daily(self, daily: AttendanceDaily) -> AttendanceDaily:
        if daily.id is None:
            self.session.add(daily)
        await self.session.flush()
        return daily

    # ----------------------------------------------------------------- #
    # Leave compensation (driven by the approval module via events)     #
    # ----------------------------------------------------------------- #
    async def apply_leave(
        self,
        employee_id: int,
        start: date,
        end: date,
        *,
        paid: bool,
        leave_type: str,
    ) -> int:
        """Mark each day in [start, end] as LEAVE. Credits a full day when paid.

        Returns the number of days marked.
        """
        days = 0
        cursor = start
        while cursor <= end:
            daily = await self.daily.get_for(employee_id, cursor)
            if daily is None:
                daily = AttendanceDaily(employee_id=employee_id, work_date=cursor)
                self.session.add(daily)
            daily.status = DailyStatus.LEAVE
            daily.work_value = _FULL if paid else _ZERO
            daily.note = f"LEAVE:{leave_type}"
            days += 1
            cursor += timedelta(days=1)
        await self.session.flush()
        logger.info("attendance_apply_leave", employee_id=employee_id, days=days, paid=paid)
        return days

    # ----------------------------------------------------------------- #
    # Monthly aggregation                                               #
    # ----------------------------------------------------------------- #
    async def aggregate_monthly(self, period: str, *, standard_days: Decimal | None = None) -> int:
        """Aggregate daily -> monthly for a 'YYYY-MM' period (lock-guarded).

        Locked rows (period finalised by payroll) are never overwritten.
        Returns the number of employee rows inserted/updated.
        """
        if standard_days is None:
            standard_days = await self._infer_standard_days(period)

        result = await self.session.execute(
            text(
                """
                INSERT INTO attendance_monthly
                    (employee_id, period, standard_days, actual_days, leave_days,
                     paid_leave_days, ot_hours, late_count)
                SELECT
                    d.employee_id,
                    :period,
                    :standard_days,
                    COALESCE(SUM(CASE WHEN d.status='NORMAL' THEN d.work_value ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN d.status='LEAVE'  THEN d.work_value ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN d.status='LEAVE' AND d.work_value > 0
                                      THEN d.work_value ELSE 0 END), 0),
                    COALESCE(SUM(d.ot_minutes), 0) / 60.0,
                    COUNT(*) FILTER (WHERE d.late_minutes > 0)
                FROM attendance_daily d
                WHERE to_char(d.work_date, 'YYYY-MM') = :period
                GROUP BY d.employee_id
                ON CONFLICT (employee_id, period) DO UPDATE SET
                    standard_days   = EXCLUDED.standard_days,
                    actual_days     = EXCLUDED.actual_days,
                    leave_days      = EXCLUDED.leave_days,
                    paid_leave_days = EXCLUDED.paid_leave_days,
                    ot_hours        = EXCLUDED.ot_hours,
                    late_count      = EXCLUDED.late_count,
                    updated_at      = now()
                WHERE attendance_monthly.locked = FALSE
                """
            ),
            {"period": period, "standard_days": standard_days},
        )
        await self.session.flush()
        affected: int = result.rowcount  # type: ignore[attr-defined]
        logger.info("attendance_aggregate_monthly", period=period, employees=affected)
        return affected

    async def recompute_monthly(self, employee_id: int, period: str) -> None:
        """Recompute one employee's monthly aggregate (used after a leave/adjust)."""
        await self.aggregate_monthly(period)

    async def _infer_standard_days(self, period: str) -> Decimal:
        """Standard working days = distinct work_dates present for the period."""
        count = (
            await self.session.execute(
                text(
                    "SELECT COUNT(DISTINCT work_date) FROM attendance_daily "
                    "WHERE to_char(work_date, 'YYYY-MM') = :period"
                ),
                {"period": period},
            )
        ).scalar_one()
        return Decimal(count or 0)

    # ----------------------------------------------------------------- #
    # Manual adjustment (audited)                                       #
    # ----------------------------------------------------------------- #
    async def adjust_daily(
        self,
        daily_id: int,
        *,
        status: str | None,
        work_value: Decimal | None,
        note: str | None,
        actor: CurrentUser,
        ip: str | None,
    ) -> AttendanceDaily:
        """HR override of a computed daily record. Always audited."""
        daily = await self.daily.get(daily_id)
        if daily is None:
            raise NotFoundError("Không tìm thấy bản ghi chấm công")

        old = {
            "status": daily.status,
            "work_value": str(daily.work_value),
            "note": daily.note,
        }
        if status is not None:
            if status not in DailyStatus.ALL:
                raise ConflictError("Trạng thái không hợp lệ")
            daily.status = status
        if work_value is not None:
            daily.work_value = work_value
        if note is not None:
            daily.note = note
        await self.session.flush()

        await record(
            self.session,
            actor_id=actor.id,
            action="UPDATE",
            entity="attendance_daily",
            entity_id=daily.id,
            old=old,
            new={
                "status": daily.status,
                "work_value": str(daily.work_value),
                "note": daily.note,
            },
            ip=ip,
        )
        return daily

    # ----------------------------------------------------------------- #
    # Simple config CRUD                                                #
    # ----------------------------------------------------------------- #
    async def create_device(
        self, *, code: str, name: str, adapter_type: str, config: dict, is_active: bool
    ) -> AttendanceDevice:
        if await self.devices.get_by_code(code):
            raise ConflictError("Mã thiết bị đã tồn tại")
        device = AttendanceDevice(
            code=code, name=name, adapter_type=adapter_type, config=config, is_active=is_active
        )
        return await self.devices.add(device)

    async def create_shift(self, shift: Shift) -> Shift:
        if await self.shifts.get_by_code(shift.code):
            raise ConflictError("Mã ca làm việc đã tồn tại")
        return await self.shifts.add(shift)

    async def create_holiday(self, holiday: Holiday) -> Holiday:
        if await self.holidays.get_on(holiday.holiday_date):
            raise ConflictError("Ngày lễ đã tồn tại")
        return await self.holidays.add(holiday)
