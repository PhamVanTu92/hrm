"""Seed a large employee population and benchmark a payroll run.

Usage (inside the backend env, DB reachable):

    python -m loadtest.seed_payroll seed --count 10000 --period 2026-05
    python -m loadtest.seed_payroll bench --period 2026-05

``seed`` inserts N employees + their monthly attendance + the salary
components/formulas needed for a realistic run. ``bench`` times a full
``calculate_run`` over the whole population and prints the throughput.

For production-scale runs the same ``calculate_run`` is driven in parallel by
the Celery chord (app.workers.payroll_tasks.run_payroll); this script measures
the single-process baseline.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.encryption import encrypt_decimal
from app.core.exceptions import ConflictError
from app.core.rbac import CurrentUser
from app.db.session import SessionLocal, dispose_engines
from app.modules.attendance.models import AttendanceMonthly
from app.modules.employee.models import Employee
from app.modules.payroll.models import SalaryComponent, SalaryComponentAssignment
from app.modules.payroll.service import PayrollService

_BATCH = 1000
_ACTOR = CurrentUser(id=1, perms={"payroll:run", "payroll:lock"})


async def _ensure_components(svc: PayrollService) -> None:
    """Create the standard component set once (idempotent)."""
    existing = {c.var_code for c in (await svc.session.execute(select(SalaryComponent))).scalars()}
    specs = [
        {
            "code": "PC_AN",
            "name": "Phụ cấp ăn",
            "value_type": "FIXED",
            "var_code": "phu_cap_an",
            "default_value": Decimal("730000"),
        },
        {"code": "THUONG", "name": "Thưởng", "value_type": "INPUT", "var_code": "thuong"},
        {
            "code": "LUONG_THANG",
            "name": "Lương tháng",
            "value_type": "FORMULA",
            "var_code": "luong_thang",
            "expression": "round(luong_cung / cong_chuan * cong_thuc_te, 2)",
        },
        {
            "code": "TONG",
            "name": "Tổng lương",
            "value_type": "FORMULA",
            "var_code": "TONG_LUONG",
            "expression": "luong_thang + phu_cap_an + thuong",
        },
    ]
    for spec in specs:
        if spec["var_code"] in existing:
            continue
        try:
            comp = await svc.create_component(**spec)  # type: ignore[arg-type]
        except ConflictError:
            continue
        if comp.value_type in ("FIXED", "INPUT"):
            svc.session.add(
                SalaryComponentAssignment(
                    component_id=comp.id, scope="ALL", effective_from=date(2026, 1, 1)
                )
            )
    await svc.session.flush()


async def seed(count: int, period: str) -> None:
    async with SessionLocal() as session:
        svc = PayrollService(session)
        await svc.get_or_create_period(period)
        await _ensure_components(svc)
        await session.commit()

        salary = Decimal("15000000")
        std = Decimal("22")
        for start in range(0, count, _BATCH):
            employees = [
                Employee(
                    employee_code=f"LT{i:06d}",
                    full_name=f"Load Test {i}",
                    enc_base_salary=encrypt_decimal(salary),
                )
                for i in range(start, min(start + _BATCH, count))
            ]
            session.add_all(employees)
            await session.flush()
            session.add_all(
                AttendanceMonthly(
                    employee_id=e.id,
                    period=period,
                    standard_days=std,
                    actual_days=std,
                    ot_hours=Decimal("0"),
                )
                for e in employees
            )
            await session.commit()
            print(f"  seeded {min(start + _BATCH, count)}/{count}")
        print(f"Seed done: {count} employees for {period}")


async def bench(period: str) -> None:
    async with SessionLocal() as session:
        svc = PayrollService(session)
        emp_ids = list((await session.execute(select(Employee.id))).scalars().all())
        period_obj = await svc.get_or_create_period(period)
        run = await svc.runs.active_for_period(period_obj.id)
        if run is None:
            run = await svc.create_run(period, _ACTOR)
            await session.commit()

        t0 = time.perf_counter()
        n = await svc.calculate_run(run.id, employee_ids=emp_ids)
        await session.commit()
        dt = time.perf_counter() - t0
        rate = n / dt if dt else 0
        print(f"Calculated {n} employees in {dt:.2f}s ({rate:,.0f} emp/s) [run #{run.id}]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Payroll load-test seeding + benchmark")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("--count", type=int, default=10000)
    s.add_argument("--period", default="2026-05")
    b = sub.add_parser("bench")
    b.add_argument("--period", default="2026-05")
    args = parser.parse_args()

    async def _run() -> None:
        try:
            if args.cmd == "seed":
                await seed(args.count, args.period)
            else:
                await bench(args.period)
        finally:
            await dispose_engines()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
