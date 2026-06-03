"""Request context middleware: correlation id + structured request logging."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_request_context, clear_request_context, get_logger

logger = get_logger("http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign an ``X-Request-ID``, bind it to logs, and log each request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        bind_request_context(request_id=request_id, path=request.url.path, method=request.method)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_failed")
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "request_completed",
                duration_ms=duration_ms,
                user_id=getattr(request.state, "user_id", None),
            )
            clear_request_context()

        response.headers["X-Request-ID"] = request_id
        return response
