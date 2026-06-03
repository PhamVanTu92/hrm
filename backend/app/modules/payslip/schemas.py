"""Pydantic schemas for the payslip module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PayslipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_item_id: int
    employee_id: int
    period: str
    file_id: int | None
    status: str
    email_status: str
    pwd_hint: str | None
    feedback: str | None
    confirmed_at: datetime | None
    sent_at: datetime | None


class FeedbackRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
