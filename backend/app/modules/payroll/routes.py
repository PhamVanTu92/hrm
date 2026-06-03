"""Payroll API routes: component/formula config, period & run lifecycle,
Excel input import/template, and overrides.

Authorization:
  * payroll:read  -> view components, runs, items
  * payroll:run   -> configure components, create/calculate runs, import input
  * payroll:lock  -> lock / cancel a run
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.pagination import Envelope
from app.core.rbac import CurrentUser, require_perm
from app.db.session import get_db
from app.modules.payroll.repository import ComponentRepository, RunItemRepository, RunRepository
from app.modules.payroll.schemas import (
    CalculateRequest,
    ComponentCreate,
    ComponentOut,
    OverrideCreate,
    PeriodCreate,
    RunCreate,
    RunItemOut,
    RunOut,
)
from app.modules.payroll.service import PayrollService

router = APIRouter(prefix="/payroll", tags=["payroll"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# --------------------------------------------------------------------------- #
# Components                                                                  #
# --------------------------------------------------------------------------- #
@router.post(
    "/components", response_model=Envelope[ComponentOut], status_code=status.HTTP_201_CREATED
)
async def create_component(
    payload: ComponentCreate,
    db: DbDep,
    _: CurrentUser = require_perm("payroll:run"),
) -> Envelope[ComponentOut]:
    component = await PayrollService(db).create_component(
        code=payload.code,
        name=payload.name,
        value_type=payload.value_type,
        var_code=payload.var_code,
        default_value=payload.default_value,
        expression=payload.expression,
    )
    return Envelope(data=ComponentOut.model_validate(component))


@router.get("/components", response_model=Envelope[list[ComponentOut]])
async def list_components(
    db: DbDep,
    _: CurrentUser = require_perm("payroll:read"),
) -> Envelope[list[ComponentOut]]:
    rows = await ComponentRepository(db).active()
    return Envelope(data=[ComponentOut.model_validate(c) for c in rows])


# --------------------------------------------------------------------------- #
# Periods                                                                     #
# --------------------------------------------------------------------------- #
@router.post("/periods", response_model=Envelope[dict], status_code=status.HTTP_201_CREATED)
async def create_period(
    payload: PeriodCreate,
    db: DbDep,
    _: CurrentUser = require_perm("payroll:run"),
) -> Envelope[dict]:
    period = await PayrollService(db).get_or_create_period(
        payload.code, standard_days=payload.standard_days
    )
    return Envelope(data={"id": period.id, "code": period.code, "status": period.status})


# --------------------------------------------------------------------------- #
# Runs                                                                        #
# --------------------------------------------------------------------------- #
@router.post("/runs", response_model=Envelope[RunOut], status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: RunCreate,
    request: Request,
    db: DbDep,
    user: CurrentUser = require_perm("payroll:run"),
) -> Envelope[RunOut]:
    run = await PayrollService(db).create_run(payload.period_code, user, ip=_ip(request))
    return Envelope(data=RunOut.model_validate(run))


@router.post("/runs/{run_id}/calculate", response_model=Envelope[dict])
async def calculate_run(
    run_id: int,
    payload: CalculateRequest,
    db: DbDep,
    _: CurrentUser = require_perm("payroll:run"),
) -> Envelope[dict]:
    # Synchronous for moderate sizes; large runs go via the Celery chord
    # (app.workers.payroll_tasks.run_payroll) which calls this same service.
    count = await PayrollService(db).calculate_run(run_id, employee_ids=payload.employee_ids)
    return Envelope(data={"run_id": run_id, "calculated": count})


@router.post("/runs/{run_id}/lock", response_model=Envelope[RunOut])
async def lock_run(
    run_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUser = require_perm("payroll:lock"),
) -> Envelope[RunOut]:
    run = await PayrollService(db).lock_run(run_id, user, ip=_ip(request))
    return Envelope(data=RunOut.model_validate(run))


@router.post("/runs/{run_id}/cancel", response_model=Envelope[RunOut])
async def cancel_run(
    run_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUser = require_perm("payroll:lock"),
) -> Envelope[RunOut]:
    run = await PayrollService(db).cancel_run(run_id, user, ip=_ip(request))
    return Envelope(data=RunOut.model_validate(run))


@router.get("/runs/{run_id}", response_model=Envelope[RunOut])
async def get_run(
    run_id: int,
    db: DbDep,
    _: CurrentUser = require_perm("payroll:read"),
) -> Envelope[RunOut]:
    run = await RunRepository(db).get(run_id)
    if run is None:
        raise NotFoundError("Không tìm thấy bảng tính lương")
    return Envelope(data=RunOut.model_validate(run))


@router.get("/runs/{run_id}/items", response_model=Envelope[list[RunItemOut]])
async def list_run_items(
    run_id: int,
    db: DbDep,
    _: CurrentUser = require_perm("payroll:read"),
) -> Envelope[list[RunItemOut]]:
    items = await RunItemRepository(db).list_for_run(run_id)
    return Envelope(data=[RunItemOut.model_validate(i) for i in items])


# --------------------------------------------------------------------------- #
# Excel input                                                                 #
# --------------------------------------------------------------------------- #
@router.get("/input/template")
async def download_template(
    db: DbDep,
    period: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")],
    _: CurrentUser = require_perm("payroll:read"),
) -> Response:
    content = await PayrollService(db).generate_template(period)
    return Response(
        content=content,
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="payroll_input_{period}.xlsx"'},
    )


@router.post("/input/import", response_model=Envelope[dict])
async def import_input(
    db: DbDep,
    period: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")],
    file: Annotated[UploadFile, File()],
    _: CurrentUser = require_perm("payroll:run"),
) -> Envelope[dict[str, Any]]:
    content = await file.read()
    report = await PayrollService(db).import_input(period_code=period, file_bytes=content)
    return Envelope(data=report)


# --------------------------------------------------------------------------- #
# Overrides                                                                   #
# --------------------------------------------------------------------------- #
@router.post("/overrides", response_model=Envelope[dict], status_code=status.HTTP_201_CREATED)
async def set_override(
    payload: OverrideCreate,
    db: DbDep,
    _: CurrentUser = require_perm("payroll:run"),
) -> Envelope[dict]:
    await PayrollService(db).set_override(
        period_code=payload.period_code, employee_id=payload.employee_id, data=payload.data
    )
    return Envelope(data={"status": "ok"})
