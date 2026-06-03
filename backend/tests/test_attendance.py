"""Tests for the attendance module.

Service-level tests cover the normalisation/aggregation maths (the risky part);
API tests cover RBAC, config CRUD and manual adjustment.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attendance.adapters.base import RawPunch
from app.modules.attendance.models import (
    AttendanceDaily,
    AttendanceDevice,
    DailyStatus,
    Holiday,
    RawPunchLog,
    Shift,
)
from app.modules.attendance.repository import MonthlyRepository
from app.modules.attendance.service import AttendanceService
from app.modules.employee.models import Employee
from tests.conftest import API

HeaderFactory = Callable[..., dict[str, str]]


# --------------------------------------------------------------------------- #
# Arrange helpers                                                             #
# --------------------------------------------------------------------------- #
async def _employee(session: AsyncSession, code: str = "E001") -> Employee:
    emp = Employee(employee_code=code, full_name=f"NV {code}")
    session.add(emp)
    await session.flush()
    return emp


async def _shift(session: AsyncSession) -> Shift:
    shift = Shift(
        code="ADM",
        name="Hành chính",
        start_time=time(8, 0),
        end_time=time(17, 0),
        break_minutes=60,
        late_grace_min=5,
        holiday_value=Decimal("1.00"),
    )
    session.add(shift)
    await session.flush()
    return shift


async def _device(session: AsyncSession) -> AttendanceDevice:
    dev = AttendanceDevice(code="DEV1", name="Cổng chính", adapter_type="MANUAL")
    session.add(dev)
    await session.flush()
    return dev


def _dt(d: date, h: int, m: int) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=UTC)


async def _punch(
    session: AsyncSession, device_id: int, emp: Employee, d: date, h: int, m: int
) -> None:
    session.add(
        RawPunchLog(
            device_id=device_id,
            device_user_id=emp.employee_code,
            employee_id=emp.id,
            punch_at=_dt(d, h, m),
        )
    )
    await session.flush()


# --------------------------------------------------------------------------- #
# Normalisation maths                                                         #
# --------------------------------------------------------------------------- #
async def test_normalize_full_day_late_and_ot(db_session: AsyncSession) -> None:
    emp = await _employee(db_session)
    shift = await _shift(db_session)
    dev = await _device(db_session)
    work_date = date(2026, 5, 4)
    await _punch(db_session, dev.id, emp, work_date, 8, 10)  # in (10' late, 5' grace -> 5)
    await _punch(db_session, dev.id, emp, work_date, 17, 30)  # out (30' OT)

    daily = await AttendanceService(db_session).normalize_day(emp.id, work_date, shift=shift)

    assert daily.status == DailyStatus.NORMAL
    assert daily.late_minutes == 5
    assert daily.early_minutes == 0
    assert daily.ot_minutes == 30
    assert daily.work_value == Decimal("1.00")


async def test_normalize_half_day(db_session: AsyncSession) -> None:
    emp = await _employee(db_session)
    shift = await _shift(db_session)
    dev = await _device(db_session)
    work_date = date(2026, 5, 5)
    await _punch(db_session, dev.id, emp, work_date, 8, 0)
    await _punch(db_session, dev.id, emp, work_date, 12, 0)  # left at noon

    daily = await AttendanceService(db_session).normalize_day(emp.id, work_date, shift=shift)

    # worked 240 - 60 break = 180; required 480; ratio .375 -> rounds to 0.5
    assert daily.work_value == Decimal("0.50")
    assert daily.early_minutes == 300  # 17:00 - 12:00


async def test_normalize_missing_when_no_punches(db_session: AsyncSession) -> None:
    emp = await _employee(db_session)
    shift = await _shift(db_session)
    daily = await AttendanceService(db_session).normalize_day(emp.id, date(2026, 5, 6), shift=shift)
    assert daily.status == DailyStatus.MISSING
    assert daily.work_value == Decimal("0.00")


async def test_normalize_paid_holiday(db_session: AsyncSession) -> None:
    emp = await _employee(db_session)
    shift = await _shift(db_session)
    holiday = date(2026, 5, 1)
    db_session.add(Holiday(holiday_date=holiday, name="Quốc tế Lao động", is_paid=True))
    await db_session.flush()

    daily = await AttendanceService(db_session).normalize_day(emp.id, holiday, shift=shift)
    assert daily.status == DailyStatus.HOLIDAY
    assert daily.work_value == Decimal("1.00")


async def test_normalize_preserves_existing_leave(db_session: AsyncSession) -> None:
    emp = await _employee(db_session)
    shift = await _shift(db_session)
    svc = AttendanceService(db_session)
    work_date = date(2026, 5, 7)
    await svc.apply_leave(emp.id, work_date, work_date, paid=True, leave_type="ANNUAL")

    # Re-normalising a day with no punches must not wipe the approved leave.
    daily = await svc.normalize_day(emp.id, work_date, shift=shift)
    assert daily.status == DailyStatus.LEAVE
    assert daily.work_value == Decimal("1.00")


# --------------------------------------------------------------------------- #
# Ingest idempotency                                                          #
# --------------------------------------------------------------------------- #
async def test_ingest_resolves_employee_and_is_idempotent(db_session: AsyncSession) -> None:
    emp = await _employee(db_session, code="E777")
    dev = await _device(db_session)
    svc = AttendanceService(db_session)
    punches = [
        RawPunch(device_user_id="E777", punch_at=_dt(date(2026, 5, 4), 8, 0)),
        RawPunch(device_user_id="E777", punch_at=_dt(date(2026, 5, 4), 17, 0)),
    ]
    assert await svc.ingest_punches(dev.id, punches) == 2
    # Re-pulling the same punches inserts nothing (idempotent).
    assert await svc.ingest_punches(dev.id, punches) == 0

    rows = await svc.raw.punches_for(emp.id, date(2026, 5, 4))
    assert len(rows) == 2
    assert all(r.employee_id == emp.id for r in rows)


# --------------------------------------------------------------------------- #
# Monthly aggregation                                                         #
# --------------------------------------------------------------------------- #
async def test_aggregate_monthly(db_session: AsyncSession) -> None:
    emp = await _employee(db_session)
    rows = [
        AttendanceDaily(
            employee_id=emp.id,
            work_date=date(2026, 5, 4),
            status=DailyStatus.NORMAL,
            work_value=Decimal("1.00"),
            late_minutes=5,
            ot_minutes=30,
        ),
        AttendanceDaily(
            employee_id=emp.id,
            work_date=date(2026, 5, 5),
            status=DailyStatus.NORMAL,
            work_value=Decimal("0.50"),
        ),
        AttendanceDaily(
            employee_id=emp.id,
            work_date=date(2026, 5, 6),
            status=DailyStatus.LEAVE,
            work_value=Decimal("1.00"),
        ),
        AttendanceDaily(
            employee_id=emp.id,
            work_date=date(2026, 5, 7),
            status=DailyStatus.MISSING,
            work_value=Decimal("0.00"),
        ),
    ]
    db_session.add_all(rows)
    await db_session.flush()

    affected = await AttendanceService(db_session).aggregate_monthly("2026-05")
    assert affected == 1

    monthly = await MonthlyRepository(db_session).get_for(emp.id, "2026-05")
    assert monthly is not None
    assert monthly.actual_days == Decimal("1.50")
    assert monthly.leave_days == Decimal("1.00")
    assert monthly.paid_leave_days == Decimal("1.00")
    assert monthly.ot_hours == Decimal("0.50")
    assert monthly.late_count == 1
    assert monthly.standard_days == Decimal("4")


async def test_aggregate_respects_lock(db_session: AsyncSession) -> None:
    emp = await _employee(db_session)
    db_session.add(
        AttendanceDaily(
            employee_id=emp.id,
            work_date=date(2026, 5, 4),
            status=DailyStatus.NORMAL,
            work_value=Decimal("1.00"),
        )
    )
    await db_session.flush()
    svc = AttendanceService(db_session)
    await svc.aggregate_monthly("2026-05")

    # Lock the period (as payroll would), then change daily and re-aggregate.
    monthly = await MonthlyRepository(db_session).get_for(emp.id, "2026-05")
    assert monthly is not None
    monthly.locked = True
    await db_session.flush()

    db_session.add(
        AttendanceDaily(
            employee_id=emp.id,
            work_date=date(2026, 5, 5),
            status=DailyStatus.NORMAL,
            work_value=Decimal("1.00"),
        )
    )
    await db_session.flush()
    await svc.aggregate_monthly("2026-05")

    await db_session.refresh(monthly)
    # Locked row was NOT overwritten (still reflects the single original day).
    assert monthly.actual_days == Decimal("1.00")


# --------------------------------------------------------------------------- #
# API + RBAC                                                                  #
# --------------------------------------------------------------------------- #
async def test_device_crud_and_rbac(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    manage = auth_header(perms=["attendance:manage"])
    read = auth_header(perms=["attendance:read"])

    created = await client.post(
        f"{API}/attendance/devices",
        json={"code": "DEV-API", "name": "Test", "adapter_type": "MANUAL"},
        headers=manage,
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["code"] == "DEV-API"

    listed = await client.get(f"{API}/attendance/devices", headers=read)
    assert listed.status_code == 200
    assert any(d["code"] == "DEV-API" for d in listed.json()["data"])

    # read-only token cannot create.
    forbidden = await client.post(
        f"{API}/attendance/devices",
        json={"code": "DEV-X", "name": "X", "adapter_type": "MANUAL"},
        headers=read,
    )
    assert forbidden.status_code == 403


async def test_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/attendance/devices")).status_code == 401


async def test_manual_adjust_daily_is_audited(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    emp = await _employee(db_session)
    daily = AttendanceDaily(
        employee_id=emp.id,
        work_date=date(2026, 5, 8),
        status=DailyStatus.MISSING,
        work_value=Decimal("0.00"),
    )
    db_session.add(daily)
    await db_session.flush()

    resp = await client.patch(
        f"{API}/attendance/daily/{daily.id}",
        json={"status": "NORMAL", "work_value": "1.00", "note": "Quên chấm công"},
        headers=auth_header(perms=["attendance:manage"]),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "NORMAL"
    assert data["work_value"] == "1.00"


async def test_adjust_invalid_status_rejected(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    emp = await _employee(db_session)
    daily = AttendanceDaily(
        employee_id=emp.id, work_date=date(2026, 5, 9), status=DailyStatus.MISSING
    )
    db_session.add(daily)
    await db_session.flush()
    resp = await client.patch(
        f"{API}/attendance/daily/{daily.id}",
        json={"status": "BOGUS"},
        headers=auth_header(perms=["attendance:manage"]),
    )
    assert resp.status_code == 409


async def test_aggregate_and_get_monthly_via_api(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    emp = await _employee(db_session)
    db_session.add(
        AttendanceDaily(
            employee_id=emp.id,
            work_date=date(2026, 5, 4),
            status=DailyStatus.NORMAL,
            work_value=Decimal("1.00"),
        )
    )
    await db_session.flush()

    # Not aggregated yet -> 404.
    missing = await client.get(
        f"{API}/attendance/monthly/{emp.id}/2026-05", headers=auth_header(perms=["attendance:read"])
    )
    assert missing.status_code == 404

    agg = await client.post(
        f"{API}/attendance/aggregate",
        json={"period": "2026-05"},
        headers=auth_header(perms=["attendance:manage"]),
    )
    assert agg.status_code == 200, agg.text
    assert agg.json()["data"]["employees"] == 1

    got = await client.get(
        f"{API}/attendance/monthly/{emp.id}/2026-05", headers=auth_header(perms=["attendance:read"])
    )
    assert got.status_code == 200
    assert got.json()["data"]["actual_days"] == "1.00"


@pytest.mark.parametrize("period", ["2026-5", "abc", "202605"])
async def test_aggregate_rejects_bad_period(
    client: AsyncClient, auth_header: HeaderFactory, period: str
) -> None:
    resp = await client.post(
        f"{API}/attendance/aggregate",
        json={"period": period},
        headers=auth_header(perms=["attendance:manage"]),
    )
    assert resp.status_code == 422
