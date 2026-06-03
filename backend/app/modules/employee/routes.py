"""Employee + dynamic profile API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Envelope, Page, PageParams, page_params
from app.core.rbac import CurrentUser, CurrentUserDep, require_perm
from app.db.session import get_db
from app.modules.employee.schemas import (
    DynamicProfileOut,
    DynamicProfileUpdate,
    EmployeeCreate,
    EmployeeFilter,
    EmployeeOut,
    EmployeeSensitiveOut,
    EmployeeUpdate,
    ProfileCategoryCreate,
    ProfileCategoryOut,
    ProfileFieldCreate,
    ProfileFieldMetaOut,
    employee_filter,
)
from app.modules.employee.service import EmployeeService

router = APIRouter(prefix="/employees", tags=["employees"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=Page[EmployeeOut])
async def list_employees(
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    filters: Annotated[EmployeeFilter, Depends(employee_filter)],
    _: CurrentUser = require_perm("employee:read"),
) -> Page[EmployeeOut]:
    """Paginated, filterable, sortable employee list."""
    rows, total = await EmployeeService(db).list_employees(params, filters)
    return Page.create([EmployeeOut.model_validate(r) for r in rows], total, params)


@router.post("", response_model=Envelope[EmployeeOut], status_code=status.HTTP_201_CREATED)
async def create_employee(
    payload: EmployeeCreate,
    request: Request,
    db: DbDep,
    user: CurrentUser = require_perm("employee:write"),
) -> Envelope[EmployeeOut]:
    emp = await EmployeeService(db).create(payload, user, _ip(request))
    return Envelope(data=EmployeeOut.model_validate(emp))


# --------------------------------------------------------------------------- #
# Dynamic field metadata (settings/dynamic-fields). Declared BEFORE the
# /{employee_id} routes so these literal paths win over the int path param.
# --------------------------------------------------------------------------- #
@router.get("/profile-fields", response_model=Envelope[list[ProfileFieldMetaOut]])
async def list_profile_fields(
    db: DbDep,
    _: CurrentUser = require_perm("employee:read"),
) -> Envelope[list[ProfileFieldMetaOut]]:
    """Active dynamic-field definitions that drive the dynamic profile form."""
    fields = await EmployeeService(db).list_fields()
    return Envelope(data=[ProfileFieldMetaOut.model_validate(f) for f in fields])


@router.post(
    "/profile-fields",
    response_model=Envelope[ProfileFieldMetaOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_profile_field(
    payload: ProfileFieldCreate,
    db: DbDep,
    _: CurrentUser = require_perm("dynamic_field:manage"),
) -> Envelope[ProfileFieldMetaOut]:
    field = await EmployeeService(db).create_field(
        category_id=payload.category_id,
        field_key=payload.field_key,
        label=payload.label,
        data_type=payload.data_type,
        options=payload.options,
        is_required=payload.is_required,
        is_encrypted=payload.is_encrypted,
    )
    return Envelope(data=ProfileFieldMetaOut.model_validate(field))


@router.get("/profile-categories", response_model=Envelope[list[ProfileCategoryOut]])
async def list_profile_categories(
    db: DbDep,
    _: CurrentUser = require_perm("employee:read"),
) -> Envelope[list[ProfileCategoryOut]]:
    cats = await EmployeeService(db).list_categories()
    return Envelope(data=[ProfileCategoryOut.model_validate(c) for c in cats])


@router.post(
    "/profile-categories",
    response_model=Envelope[ProfileCategoryOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_profile_category(
    payload: ProfileCategoryCreate,
    db: DbDep,
    _: CurrentUser = require_perm("dynamic_field:manage"),
) -> Envelope[ProfileCategoryOut]:
    cat = await EmployeeService(db).create_category(
        code=payload.code, name=payload.name, sort_order=payload.sort_order
    )
    return Envelope(data=ProfileCategoryOut.model_validate(cat))


@router.get("/{employee_id}", response_model=Envelope[EmployeeOut])
async def get_employee(
    employee_id: int,
    db: DbDep,
    _: CurrentUser = require_perm("employee:read"),
) -> Envelope[EmployeeOut]:
    emp = await EmployeeService(db).get(employee_id)
    return Envelope(data=EmployeeOut.model_validate(emp))


@router.get("/{employee_id}/sensitive", response_model=Envelope[EmployeeSensitiveOut])
async def get_employee_sensitive(
    employee_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUser = require_perm("salary:view_sensitive"),
) -> Envelope[EmployeeSensitiveOut]:
    """Decrypted sensitive fields. Access is recorded in the audit log."""
    data = await EmployeeService(db).get_sensitive(employee_id, user, _ip(request))
    return Envelope(data=data)


@router.patch("/{employee_id}", response_model=Envelope[EmployeeOut])
async def update_employee(
    employee_id: int,
    payload: EmployeeUpdate,
    request: Request,
    db: DbDep,
    user: CurrentUser = require_perm("employee:write"),
) -> Envelope[EmployeeOut]:
    emp = await EmployeeService(db).update(employee_id, payload, user, _ip(request))
    return Envelope(data=EmployeeOut.model_validate(emp))


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_employee(
    employee_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUser = require_perm("employee:write"),
) -> None:
    await EmployeeService(db).delete(employee_id, user, _ip(request))


@router.get("/{employee_id}/profile", response_model=Envelope[DynamicProfileOut])
async def get_profile(
    employee_id: int,
    db: DbDep,
    user: CurrentUserDep,
) -> Envelope[DynamicProfileOut]:
    data = await EmployeeService(db).get_profile(employee_id, user)
    return Envelope(data=data)


@router.put("/{employee_id}/profile", response_model=Envelope[DynamicProfileOut])
async def save_profile(
    employee_id: int,
    payload: DynamicProfileUpdate,
    request: Request,
    db: DbDep,
    user: CurrentUser = require_perm("employee:write"),
) -> Envelope[DynamicProfileOut]:
    data = await EmployeeService(db).save_profile(employee_id, payload.data, user, _ip(request))
    return Envelope(data=data)
