"""Pydantic schemas for the employee module."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field


class EmployeeCreate(BaseModel):
    employee_code: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=2, max_length=200)
    department_id: int | None = None
    position_id: int | None = None
    manager_id: int | None = None
    join_date: date | None = None
    user_id: int | None = None
    # Sensitive (plaintext in; encrypted at rest)
    national_id: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=20)
    bank_account: str | None = Field(default=None, max_length=40)
    base_salary: Decimal | None = None


class EmployeeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    department_id: int | None = None
    position_id: int | None = None
    manager_id: int | None = None
    status: str | None = None
    national_id: str | None = None
    phone: str | None = None
    bank_account: str | None = None
    base_salary: Decimal | None = None


class EmployeeOut(BaseModel):
    """Non-sensitive employee view (default list/detail)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_code: str
    full_name: str
    department_id: int | None
    position_id: int | None
    manager_id: int | None
    join_date: date | None
    status: str


class EmployeeSensitiveOut(BaseModel):
    """Decrypted sensitive fields — only returned with salary:view_sensitive."""

    national_id: str | None
    phone: str | None
    bank_account: str | None
    base_salary: Decimal | None


class DynamicProfileUpdate(BaseModel):
    data: dict[str, Any]


class DynamicProfileOut(BaseModel):
    employee_id: int
    data: dict[str, Any]


class ProfileCategoryCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    sort_order: int = 0


class ProfileCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    sort_order: int


class ProfileFieldCreate(BaseModel):
    category_id: int
    field_key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=200)
    data_type: str  # TEXT/NUMBER/DATE/SELECT/BOOLEAN
    options: list[str] | None = None
    is_required: bool = False
    is_encrypted: bool = False


class ProfileFieldMetaOut(BaseModel):
    """Metadata consumed by the frontend dynamic form."""

    model_config = ConfigDict(from_attributes=True)
    field_key: str
    label: str
    data_type: str
    options: list[str] | None
    is_required: bool
    is_encrypted: bool


class EmployeeFilter(BaseModel):
    """Query-string filters for the employee list endpoint."""

    department_id: int | None = None
    position_id: int | None = None
    status: str | None = None
    q: str | None = None  # name search (trigram)


def employee_filter(
    department_id: Annotated[int | None, Query()] = None,
    position_id: Annotated[int | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(description="Tìm theo tên")] = None,
) -> EmployeeFilter:
    return EmployeeFilter(department_id=department_id, position_id=position_id, status=status, q=q)
