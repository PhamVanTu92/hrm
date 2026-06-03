"""Pydantic schemas for the attendance module."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

from app.modules.attendance.models import AdapterType


# --------------------------------------------------------------------------- #
# Devices                                                                     #
# --------------------------------------------------------------------------- #
class DeviceCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    adapter_type: str = Field(default=AdapterType.MANUAL)
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    adapter_type: str
    is_active: bool
    last_ingest_at: datetime | None


# --------------------------------------------------------------------------- #
# Shifts                                                                      #
# --------------------------------------------------------------------------- #
class ShiftCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    start_time: time
    end_time: time
    break_minutes: int = Field(default=60, ge=0, le=600)
    late_grace_min: int = Field(default=0, ge=0, le=240)
    holiday_value: Decimal = Field(default=Decimal("1.00"), ge=0, le=2)
    is_active: bool = True


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    start_time: time
    end_time: time
    break_minutes: int
    late_grace_min: int
    holiday_value: Decimal
    is_active: bool


# --------------------------------------------------------------------------- #
# Holidays                                                                    #
# --------------------------------------------------------------------------- #
class HolidayCreate(BaseModel):
    holiday_date: date
    name: str = Field(min_length=1, max_length=150)
    is_paid: bool = True


class HolidayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    holiday_date: date
    name: str
    is_paid: bool


# --------------------------------------------------------------------------- #
# Daily / Monthly                                                             #
# --------------------------------------------------------------------------- #
class AttendanceDailyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: int
    work_date: date
    shift_id: int | None
    first_in: datetime | None
    last_out: datetime | None
    late_minutes: int
    early_minutes: int
    ot_minutes: int
    work_value: Decimal
    status: str
    note: str | None


class AttendanceMonthlyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_id: int
    period: str
    standard_days: Decimal
    actual_days: Decimal
    leave_days: Decimal
    paid_leave_days: Decimal
    ot_hours: Decimal
    late_count: int
    locked: bool


class DailyAdjust(BaseModel):
    """HR manual override of a computed daily record."""

    status: str | None = Field(default=None)
    work_value: Decimal | None = Field(default=None, ge=0, le=2)
    note: str | None = Field(default=None, max_length=255)


# --------------------------------------------------------------------------- #
# Pipeline triggers                                                           #
# --------------------------------------------------------------------------- #
class NormalizeRequest(BaseModel):
    device_id: int
    work_date: date


class AggregateRequest(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    standard_days: Decimal | None = Field(default=None, ge=0, le=31)


# --------------------------------------------------------------------------- #
# Query filters                                                               #
# --------------------------------------------------------------------------- #
class DailyFilter(BaseModel):
    employee_id: int
    date_from: date
    date_to: date


def daily_filter(
    employee_id: Annotated[int, Query()],
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
) -> DailyFilter:
    return DailyFilter(employee_id=employee_id, date_from=date_from, date_to=date_to)
