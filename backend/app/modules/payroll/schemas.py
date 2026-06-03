"""Pydantic schemas for the payroll module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Components                                                                  #
# --------------------------------------------------------------------------- #
class ComponentCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    value_type: str  # INPUT / FIXED / FORMULA
    var_code: str | None = Field(default=None, max_length=60)
    default_value: Decimal | None = None
    expression: str | None = None


class ComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    var_code: str
    name: str
    value_type: str
    default_value: Decimal | None
    expression: str | None
    is_active: bool


# --------------------------------------------------------------------------- #
# Periods / runs                                                              #
# --------------------------------------------------------------------------- #
class PeriodCreate(BaseModel):
    code: str = Field(pattern=r"^\d{4}-\d{2}$")
    standard_days: Decimal | None = Field(default=None, ge=0, le=31)


class RunCreate(BaseModel):
    period_code: str = Field(pattern=r"^\d{4}-\d{2}$")


class CalculateRequest(BaseModel):
    employee_ids: list[int] | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    period_id: int
    status: str
    locked_at: datetime | None
    note: str | None


class RunItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int
    employee_id: int
    input_snapshot: dict[str, Any]
    result: dict[str, Any]
    status: str


# --------------------------------------------------------------------------- #
# Overrides                                                                   #
# --------------------------------------------------------------------------- #
class OverrideCreate(BaseModel):
    period_code: str = Field(pattern=r"^\d{4}-\d{2}$")
    employee_id: int
    data: dict[str, Any]
