"""Attendance API routes: devices, shifts, holidays, daily/monthly records,
and pipeline triggers (normalise / aggregate).

Authorization:
  * attendance:read   -> view records, devices, shifts, holidays
  * attendance:manage -> create config, trigger pipeline, manual adjust
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.pagination import Envelope, PageParams
from app.core.rbac import CurrentUser, require_perm
from app.db.session import get_db
from app.modules.attendance.models import Holiday, Shift
from app.modules.attendance.repository import (
    DailyRepository,
    DeviceRepository,
    HolidayRepository,
    MonthlyRepository,
    ShiftRepository,
)
from app.modules.attendance.schemas import (
    AggregateRequest,
    AttendanceDailyOut,
    AttendanceMonthlyOut,
    DailyAdjust,
    DailyFilter,
    DeviceCreate,
    DeviceOut,
    HolidayCreate,
    HolidayOut,
    NormalizeRequest,
    ShiftCreate,
    ShiftOut,
    daily_filter,
)
from app.modules.attendance.service import AttendanceService

router = APIRouter(prefix="/attendance", tags=["attendance"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# --------------------------------------------------------------------------- #
# Devices                                                                     #
# --------------------------------------------------------------------------- #
@router.post("/devices", response_model=Envelope[DeviceOut], status_code=status.HTTP_201_CREATED)
async def create_device(
    payload: DeviceCreate,
    db: DbDep,
    _: CurrentUser = require_perm("attendance:manage"),
) -> Envelope[DeviceOut]:
    device = await AttendanceService(db).create_device(
        code=payload.code,
        name=payload.name,
        adapter_type=payload.adapter_type,
        config=payload.config,
        is_active=payload.is_active,
    )
    return Envelope(data=DeviceOut.model_validate(device))


@router.get("/devices", response_model=Envelope[list[DeviceOut]])
async def list_devices(
    db: DbDep,
    _: CurrentUser = require_perm("attendance:read"),
) -> Envelope[list[DeviceOut]]:
    devices = await DeviceRepository(db).active_devices()
    return Envelope(data=[DeviceOut.model_validate(d) for d in devices])


# --------------------------------------------------------------------------- #
# Shifts                                                                      #
# --------------------------------------------------------------------------- #
@router.post("/shifts", response_model=Envelope[ShiftOut], status_code=status.HTTP_201_CREATED)
async def create_shift(
    payload: ShiftCreate,
    db: DbDep,
    _: CurrentUser = require_perm("attendance:manage"),
) -> Envelope[ShiftOut]:
    shift = await AttendanceService(db).create_shift(Shift(**payload.model_dump()))
    return Envelope(data=ShiftOut.model_validate(shift))


@router.get("/shifts", response_model=Envelope[list[ShiftOut]])
async def list_shifts(
    db: DbDep,
    _: CurrentUser = require_perm("attendance:read"),
) -> Envelope[list[ShiftOut]]:
    rows, _total = await ShiftRepository(db).list_page(PageParams(size=100))
    return Envelope(data=[ShiftOut.model_validate(s) for s in rows])


# --------------------------------------------------------------------------- #
# Holidays                                                                    #
# --------------------------------------------------------------------------- #
@router.post("/holidays", response_model=Envelope[HolidayOut], status_code=status.HTTP_201_CREATED)
async def create_holiday(
    payload: HolidayCreate,
    db: DbDep,
    _: CurrentUser = require_perm("attendance:manage"),
) -> Envelope[HolidayOut]:
    holiday = await AttendanceService(db).create_holiday(Holiday(**payload.model_dump()))
    return Envelope(data=HolidayOut.model_validate(holiday))


@router.get("/holidays", response_model=Envelope[list[HolidayOut]])
async def list_holidays(
    db: DbDep,
    _: CurrentUser = require_perm("attendance:read"),
) -> Envelope[list[HolidayOut]]:
    rows, _total = await HolidayRepository(db).list_page(PageParams(size=100, sort="holiday_date"))
    return Envelope(data=[HolidayOut.model_validate(h) for h in rows])


# --------------------------------------------------------------------------- #
# Daily / Monthly records                                                     #
# --------------------------------------------------------------------------- #
@router.get("/daily", response_model=Envelope[list[AttendanceDailyOut]])
async def list_daily(
    db: DbDep,
    f: Annotated[DailyFilter, Depends(daily_filter)],
    _: CurrentUser = require_perm("attendance:read"),
) -> Envelope[list[AttendanceDailyOut]]:
    rows = await DailyRepository(db).list_range(f.employee_id, f.date_from, f.date_to)
    return Envelope(data=[AttendanceDailyOut.model_validate(r) for r in rows])


@router.patch("/daily/{daily_id}", response_model=Envelope[AttendanceDailyOut])
async def adjust_daily(
    daily_id: int,
    payload: DailyAdjust,
    request: Request,
    db: DbDep,
    user: CurrentUser = require_perm("attendance:manage"),
) -> Envelope[AttendanceDailyOut]:
    daily = await AttendanceService(db).adjust_daily(
        daily_id,
        status=payload.status,
        work_value=payload.work_value,
        note=payload.note,
        actor=user,
        ip=_ip(request),
    )
    return Envelope(data=AttendanceDailyOut.model_validate(daily))


@router.get("/monthly/{employee_id}/{period}", response_model=Envelope[AttendanceMonthlyOut])
async def get_monthly(
    employee_id: int,
    period: str,
    db: DbDep,
    _: CurrentUser = require_perm("attendance:read"),
) -> Envelope[AttendanceMonthlyOut]:
    row = await MonthlyRepository(db).get_for(employee_id, period)
    if row is None:
        raise NotFoundError("Chưa có dữ liệu tổng hợp tháng")
    return Envelope(data=AttendanceMonthlyOut.model_validate(row))


# --------------------------------------------------------------------------- #
# Pipeline triggers (synchronous; the nightly run uses Celery)                #
# --------------------------------------------------------------------------- #
@router.post("/normalize", response_model=Envelope[dict])
async def normalize(
    payload: NormalizeRequest,
    db: DbDep,
    _: CurrentUser = require_perm("attendance:manage"),
) -> Envelope[dict]:
    count = await AttendanceService(db).normalize_device_day(payload.device_id, payload.work_date)
    return Envelope(data={"normalized_employees": count})


@router.post("/aggregate", response_model=Envelope[dict])
async def aggregate(
    payload: AggregateRequest,
    db: DbDep,
    _: CurrentUser = require_perm("attendance:manage"),
) -> Envelope[dict]:
    affected = await AttendanceService(db).aggregate_monthly(
        payload.period, standard_days=payload.standard_days
    )
    return Envelope(data={"period": payload.period, "employees": affected})
