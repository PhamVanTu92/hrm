"""Aggregate v1 API router. New modules register their router here."""

from __future__ import annotations

from fastapi import APIRouter

from app.audit.routes import router as audit_router
from app.modules.approval.routes import router as approval_router

# Importing this registers the LeaveApproved -> attendance handler on the bus.
from app.modules.attendance import events as _attendance_events  # noqa: F401
from app.modules.attendance.routes import router as attendance_router
from app.modules.auth.routes import router as auth_router
from app.modules.employee.routes import router as employee_router
from app.modules.payroll.routes import router as payroll_router
from app.modules.payslip.routes import router as payslip_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(employee_router)
api_router.include_router(attendance_router)
api_router.include_router(approval_router)
api_router.include_router(payroll_router)
api_router.include_router(payslip_router)
api_router.include_router(audit_router)
# api_router.include_router(payroll_router)
# api_router.include_router(payslip_router)
# api_router.include_router(notification_router)
