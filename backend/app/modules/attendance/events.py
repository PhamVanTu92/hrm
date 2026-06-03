"""Attendance event subscriptions.

When the approval module approves a leave request it publishes
:class:`LeaveApproved`; we react by compensating attendance (mark the days as
LEAVE) and recomputing the monthly aggregate.

The event carries the publisher's DB session so the side-effect runs inside the
same transaction as the approval — leave compensation and approval commit (or
roll back) atomically.

Importing this module registers the handler on the in-process event bus.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from app.core.events import subscribe
from app.core.logging import get_logger
from app.modules.attendance.service import AttendanceService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("attendance.events")


@dataclass
class LeaveApproved:
    """Published by the approval module when a leave request is approved."""

    session: AsyncSession
    employee_id: int
    start: date
    end: date
    paid: bool
    leave_type: str
    period: str  # 'YYYY-MM' to recompute


@subscribe(LeaveApproved)
async def on_leave_approved(event: LeaveApproved) -> None:
    """Compensate attendance for an approved leave and recompute the month."""
    service = AttendanceService(event.session)
    await service.apply_leave(
        event.employee_id,
        event.start,
        event.end,
        paid=event.paid,
        leave_type=event.leave_type,
    )
    await service.recompute_monthly(event.employee_id, event.period)
    logger.info("leave_compensated", employee_id=event.employee_id, period=event.period)
