"""Tests for the dynamic profile-field metadata endpoints."""

from __future__ import annotations

from collections.abc import Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.employee.service import EmployeeService
from tests.conftest import API

HeaderFactory = Callable[..., dict[str, str]]


async def test_create_category_and_field(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    manage = auth_header(perms=["dynamic_field:manage", "employee:read"])

    cat = await client.post(
        f"{API}/employees/profile-categories",
        json={"code": "PERSONAL", "name": "Cá nhân"},
        headers=manage,
    )
    assert cat.status_code == 201, cat.text
    category_id = cat.json()["data"]["id"]

    field = await client.post(
        f"{API}/employees/profile-fields",
        json={
            "category_id": category_id,
            "field_key": "tinh_trang_hon_nhan",
            "label": "Tình trạng hôn nhân",
            "data_type": "SELECT",
            "options": ["Độc thân", "Đã kết hôn"],
            "is_required": True,
        },
        headers=manage,
    )
    assert field.status_code == 201, field.text
    assert field.json()["data"]["data_type"] == "SELECT"

    listed = await client.get(
        f"{API}/employees/profile-fields", headers=auth_header(perms=["employee:read"])
    )
    assert listed.status_code == 200
    keys = [f["field_key"] for f in listed.json()["data"]]
    assert "tinh_trang_hon_nhan" in keys


async def test_create_field_requires_manage_perm(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    svc = EmployeeService(db_session)
    cat = await svc.create_category(code="C1", name="C1")
    resp = await client.post(
        f"{API}/employees/profile-fields",
        json={
            "category_id": cat.id,
            "field_key": "x",
            "label": "X",
            "data_type": "TEXT",
        },
        headers=auth_header(perms=["employee:read"]),
    )
    assert resp.status_code == 403


async def test_select_field_requires_options(db_session: AsyncSession) -> None:
    import pytest

    from app.core.exceptions import ValidationError

    svc = EmployeeService(db_session)
    cat = await svc.create_category(code="C2", name="C2")
    with pytest.raises(ValidationError):
        await svc.create_field(
            category_id=cat.id,
            field_key="bad_select",
            label="Bad",
            data_type="SELECT",
            options=None,
            is_required=False,
            is_encrypted=False,
        )


async def test_profile_fields_path_not_shadowed_by_id(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    # "/employees/profile-fields" must not be parsed as "/employees/{id}".
    resp = await client.get(
        f"{API}/employees/profile-fields", headers=auth_header(perms=["employee:read"])
    )
    assert resp.status_code == 200
