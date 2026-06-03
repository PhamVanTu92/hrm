"""Domain exceptions and FastAPI exception handlers.

All domain errors map to a stable JSON envelope::

    {"error": {"code": "...", "message": "...", "details": {...}}}

This gives the frontend machine-readable error codes while keeping messages
human-friendly (Vietnamese).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class DomainError(Exception):
    """Base class for all expected business-rule errors."""

    code: str = "DOMAIN_ERROR"
    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)


class NotFoundError(DomainError):
    code = "NOT_FOUND"
    status_code = status.HTTP_404_NOT_FOUND


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


class ConflictError(DomainError):
    code = "CONFLICT"
    status_code = status.HTTP_409_CONFLICT


class AuthenticationError(DomainError):
    code = "UNAUTHENTICATED"
    status_code = status.HTTP_401_UNAUTHORIZED


class PermissionDenied(DomainError):
    code = "FORBIDDEN"
    status_code = status.HTTP_403_FORBIDDEN


class AccountLocked(AuthenticationError):
    code = "ACCOUNT_LOCKED"
    status_code = status.HTTP_423_LOCKED


class PayrollLocked(ConflictError):
    code = "PAYROLL_LOCKED"


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the FastAPI app."""

    @app.exception_handler(DomainError)
    async def _domain_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope(
                "VALIDATION_ERROR",
                "Dữ liệu không hợp lệ",
                {"errors": exc.errors()},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope("HTTP_ERROR", str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # Never leak stack traces to the client; correlate via request id in logs.
        logger.exception(
            "unhandled_exception",
            path=request.url.path,
            request_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("INTERNAL_ERROR", "Đã xảy ra lỗi hệ thống"),
        )
