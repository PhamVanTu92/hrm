"""DB integration tests for the payroll module (service + persistence).

The pure formula maths are covered in test_payroll_engine.py; here we test
context building, run calculation + net encryption, formula-snapshot
reproducibility, locking/cancel and Excel import.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_decimal, encrypt_decimal
from app.core.exceptions import ConflictError, ValidationError
from app.core.rbac import CurrentUser
from app.modules.attendance.models import AttendanceMonthly
from app.modules.employee.models import Employee
from app.modules.payroll.models import (
    PeriodStatus,
    RunStatus,
    SalaryComponentAssignment,
)
from app.modules.payroll.repository import InputValueRepository, RunItemRepository
from app.modules.payroll.service import PayrollService
from tests.conftest import API

HeaderFactory = Callable[..., dict[str, str]]
PERIOD = "2026-05"


def _actor() -> CurrentUser:
    return CurrentUser(id=1, perms={"payroll:run", "payroll:lock"})


async def _employee(
    session: AsyncSession, code: str = "E001", salary: str = "22000000"
) -> Employee:
    emp = Employee(
        employee_code=code, full_name=code, enc_base_salary=encrypt_decimal(Decimal(salary))
    )
    session.add(emp)
    await session.flush()
    return emp


async def _monthly(session: AsyncSession, emp_id: int, actual: str = "22") -> None:
    session.add(
        AttendanceMonthly(
            employee_id=emp_id,
            period=PERIOD,
            standard_days=Decimal("22"),
            actual_days=Decimal(actual),
            ot_hours=Decimal("0"),
        )
    )
    await session.flush()


async def _assign_all(session: AsyncSession, component_id: int) -> None:
    session.add(
        SalaryComponentAssignment(
            component_id=component_id, scope="ALL", effective_from=date(2026, 1, 1)
        )
    )
    await session.flush()


async def _build_components(svc: PayrollService) -> None:
    """phu_cap_an (FIXED), thuong (INPUT), luong_thang + TONG_LUONG (FORMULA)."""
    pc = await svc.create_component(
        code="PC_AN", name="Phụ cấp ăn", value_type="FIXED", default_value=Decimal("730000")
    )
    th = await svc.create_component(code="THUONG", name="Thưởng", value_type="INPUT")
    await svc.create_component(
        code="LUONG_THANG",
        name="Lương tháng",
        value_type="FORMULA",
        var_code="luong_thang",
        expression="round(luong_cung / cong_chuan * cong_thuc_te, 2)",
    )
    await svc.create_component(
        code="TONG",
        name="Tổng lương",
        value_type="FORMULA",
        var_code="TONG_LUONG",
        expression="luong_thang + phu_cap_an + thuong",
    )
    await _assign_all(svc.session, pc.id)
    await _assign_all(svc.session, th.id)


# --------------------------------------------------------------------------- #
# Formula DAG validation at save time                                         #
# --------------------------------------------------------------------------- #
async def test_formula_cycle_rejected_on_save(db_session: AsyncSession) -> None:
    svc = PayrollService(db_session)
    await svc.create_component(
        code="A", name="A", value_type="FORMULA", var_code="a", expression="b + 1"
    )
    # b depends on a, a depends on b -> cycle, rejected at save.
    with pytest.raises(ValidationError):
        await svc.create_component(
            code="B", name="B", value_type="FORMULA", var_code="b", expression="a + 1"
        )


async def test_formula_unknown_var_rejected(db_session: AsyncSession) -> None:
    svc = PayrollService(db_session)
    with pytest.raises(ValidationError):
        await svc.create_component(
            code="X", name="X", value_type="FORMULA", var_code="x", expression="khong_co + 1"
        )


# --------------------------------------------------------------------------- #
# Context building                                                            #
# --------------------------------------------------------------------------- #
async def test_build_context(db_session: AsyncSession) -> None:
    svc = PayrollService(db_session)
    await _build_components(svc)
    emp = await _employee(db_session)
    await _monthly(db_session, emp.id, actual="20")
    period = await svc.get_or_create_period(PERIOD)
    await svc.inputs.upsert(
        period_id=period.id,
        employee_id=emp.id,
        component_id=(await svc.components.get_by_var_code("thuong")).id,
        value=Decimal("1000000"),
    )

    ctx = await svc.build_context(emp, period)
    assert ctx["luong_cung"] == 22000000.0
    assert ctx["cong_chuan"] == 22.0
    assert ctx["cong_thuc_te"] == 20.0
    assert ctx["phu_cap_an"] == 730000.0  # FIXED
    assert ctx["thuong"] == 1000000.0  # INPUT
    assert "luong_thang" not in ctx  # FORMULA not seeded


# --------------------------------------------------------------------------- #
# Full run + net encryption                                                   #
# --------------------------------------------------------------------------- #
async def test_run_calculates_and_encrypts_net(db_session: AsyncSession) -> None:
    svc = PayrollService(db_session)
    await _build_components(svc)
    emp = await _employee(db_session)
    await _monthly(db_session, emp.id, actual="22")
    period = await svc.get_or_create_period(PERIOD)
    await svc.inputs.upsert(
        period_id=period.id,
        employee_id=emp.id,
        component_id=(await svc.components.get_by_var_code("thuong")).id,
        value=Decimal("1000000"),
    )

    run = await svc.create_run(PERIOD, _actor())
    assert await svc.calculate_run(run.id) == 1

    item = await RunItemRepository(db_session).get_for(run.id, emp.id)
    assert item is not None
    # luong_thang 22,000,000 + phu_cap 730,000 + thuong 1,000,000
    assert item.result["TONG_LUONG"] == 23730000.0
    assert decrypt_decimal(item.enc_net_amount) == Decimal("23730000.0")
    # Net is encrypted at rest.
    assert b"23730000" not in bytes(item.enc_net_amount)


# --------------------------------------------------------------------------- #
# Formula-snapshot reproducibility                                            #
# --------------------------------------------------------------------------- #
async def test_run_uses_frozen_formula_snapshot(db_session: AsyncSession) -> None:
    svc = PayrollService(db_session)
    await _build_components(svc)
    emp = await _employee(db_session)
    await _monthly(db_session, emp.id)
    run = await svc.create_run(PERIOD, _actor())
    await svc.calculate_run(run.id)
    original = (await RunItemRepository(db_session).get_for(run.id, emp.id)).result["TONG_LUONG"]

    # HR edits the live formula AFTER the run was created.
    tong = await svc.components.get_by_var_code("TONG_LUONG")
    tong.expression = "(luong_thang + phu_cap_an + thuong) * 2"
    await db_session.flush()

    # Recalculating the run uses its frozen snapshot, not the live formula.
    await svc.calculate_run(run.id)
    after = (await RunItemRepository(db_session).get_for(run.id, emp.id)).result["TONG_LUONG"]
    assert after == original


# --------------------------------------------------------------------------- #
# Locking / cancel                                                            #
# --------------------------------------------------------------------------- #
async def test_lock_freezes_attendance_and_blocks_recalc(db_session: AsyncSession) -> None:
    svc = PayrollService(db_session)
    await _build_components(svc)
    emp = await _employee(db_session)
    await _monthly(db_session, emp.id)
    run = await svc.create_run(PERIOD, _actor())
    await svc.calculate_run(run.id)

    await svc.lock_run(run.id, _actor())
    period = await svc.periods.get_by_code(PERIOD)
    assert period is not None and period.status == PeriodStatus.LOCKED

    monthly = (
        await db_session.execute(
            AttendanceMonthly.__table__.select().where(AttendanceMonthly.employee_id == emp.id)
        )
    ).first()
    assert monthly is not None and monthly.locked is True

    # Locked run cannot be recalculated.
    with pytest.raises(ConflictError):
        await svc.calculate_run(run.id)


async def test_cancel_reopens_period(db_session: AsyncSession) -> None:
    svc = PayrollService(db_session)
    await _build_components(svc)
    emp = await _employee(db_session)
    await _monthly(db_session, emp.id)
    run = await svc.create_run(PERIOD, _actor())
    await svc.calculate_run(run.id)
    await svc.lock_run(run.id, _actor())

    await svc.cancel_run(run.id, _actor())
    period = await svc.periods.get_by_code(PERIOD)
    assert period is not None and period.status == PeriodStatus.OPEN


async def test_single_active_run_per_period(db_session: AsyncSession) -> None:
    svc = PayrollService(db_session)
    await _build_components(svc)
    await svc.create_run(PERIOD, _actor())
    with pytest.raises(ConflictError):
        await svc.create_run(PERIOD, _actor())


# --------------------------------------------------------------------------- #
# Maternity override                                                          #
# --------------------------------------------------------------------------- #
async def test_override_zeroes_company_salary(db_session: AsyncSession) -> None:
    svc = PayrollService(db_session)
    # Net depends on company_salary (which override sets to 0).
    await svc.create_component(
        code="NET",
        name="Net",
        value_type="FORMULA",
        var_code="TONG_LUONG",
        expression="company_salary",
    )
    emp = await _employee(db_session)
    await _monthly(db_session, emp.id)
    await svc.set_override(period_code=PERIOD, employee_id=emp.id, data={"company_salary": 0})

    run = await svc.create_run(PERIOD, _actor())
    await svc.calculate_run(run.id)
    item = await RunItemRepository(db_session).get_for(run.id, emp.id)
    assert item is not None
    assert item.result["TONG_LUONG"] == 0.0


# --------------------------------------------------------------------------- #
# Excel import                                                                #
# --------------------------------------------------------------------------- #
def _xlsx_bytes(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def test_excel_import_upserts_and_reports_errors(db_session: AsyncSession) -> None:
    svc = PayrollService(db_session)
    await svc.create_component(code="THUONG", name="Thưởng", value_type="INPUT", var_code="thuong")
    emp = await _employee(db_session, code="E100")

    content = _xlsx_bytes(
        [
            ["employee_code", "thuong"],
            ["E100", 500000],
            ["GHOST", 999],  # unknown employee -> error row
        ]
    )
    report = await svc.import_input(period_code=PERIOD, file_bytes=content)
    assert report["ok"] == 1
    assert len(report["errors"]) == 1
    assert "GHOST" in report["errors"][0]["error"]

    period = await svc.periods.get_by_code(PERIOD)
    comp = await svc.components.get_by_var_code("thuong")
    values = await InputValueRepository(db_session).map_for(period.id, emp.id)
    assert values[comp.id] == Decimal("500000")


# --------------------------------------------------------------------------- #
# API + RBAC                                                                  #
# --------------------------------------------------------------------------- #
async def test_component_create_rbac(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    body = {"code": "BASIC", "name": "Cơ bản", "value_type": "FIXED", "default_value": "1000"}
    forbidden = await client.post(
        f"{API}/payroll/components", json=body, headers=auth_header(perms=["payroll:read"])
    )
    assert forbidden.status_code == 403

    ok = await client.post(
        f"{API}/payroll/components", json=body, headers=auth_header(perms=["payroll:run"])
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["data"]["var_code"]  # auto-slugified


async def test_run_lifecycle_via_api(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    svc = PayrollService(db_session)
    await _build_components(svc)
    emp = await _employee(db_session)
    await _monthly(db_session, emp.id)

    run_perm = auth_header(perms=["payroll:run"])
    lock_perm = auth_header(perms=["payroll:lock"])

    created = await client.post(
        f"{API}/payroll/runs", json={"period_code": PERIOD}, headers=run_perm
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["data"]["id"]

    calc = await client.post(f"{API}/payroll/runs/{run_id}/calculate", json={}, headers=run_perm)
    assert calc.status_code == 200
    assert calc.json()["data"]["calculated"] == 1

    # Locking needs payroll:lock, not payroll:run.
    assert (
        await client.post(f"{API}/payroll/runs/{run_id}/lock", headers=run_perm)
    ).status_code == 403
    locked = await client.post(f"{API}/payroll/runs/{run_id}/lock", headers=lock_perm)
    assert locked.status_code == 200
    assert locked.json()["data"]["status"] == RunStatus.LOCKED
