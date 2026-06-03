"""Pydantic schemas for the approval module."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Workflow config                                                             #
# --------------------------------------------------------------------------- #
class WorkflowStepIn(BaseModel):
    step_order: int = Field(ge=1)
    approver_type: str
    approver_ref: str | None = None
    sla_hours: int = Field(default=24, ge=1, le=720)


class WorkflowCreate(BaseModel):
    target_type: str
    name: str = Field(min_length=1, max_length=150)
    steps: list[WorkflowStepIn] = Field(min_length=1)


class WorkflowStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    step_order: int
    approver_type: str
    approver_ref: str | None
    sla_hours: int


class WorkflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    target_type: str
    name: str
    is_active: bool
    steps: list[WorkflowStepOut]


# --------------------------------------------------------------------------- #
# Leave request submission                                                    #
# --------------------------------------------------------------------------- #
class LeaveRequestCreate(BaseModel):
    employee_id: int
    leave_type: str = Field(min_length=1, max_length=40)
    start_date: date
    end_date: date
    is_paid: bool = True
    reason: str | None = None


# --------------------------------------------------------------------------- #
# Actions                                                                     #
# --------------------------------------------------------------------------- #
class ApprovalAction(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- #
# Instance views                                                              #
# --------------------------------------------------------------------------- #
class StepInstanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    step_order: int
    approver_user_id: int
    due_at: datetime | None
    action: str | None
    comment: str | None
    acted_at: datetime | None
    escalated: bool


class InstanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workflow_id: int
    target_type: str
    target_id: int
    requester_id: int
    employee_id: int
    current_step: int
    status: str
    completed_at: datetime | None
    steps: list[StepInstanceOut]
