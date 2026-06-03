"""Observability: Sentry error tracking + Prometheus metrics.

Both are optional and degrade gracefully:
- Sentry initialises only when ``SENTRY_DSN`` is set and the SDK is installed.
- Prometheus uses ``prometheus-client`` (a base dependency) and exposes
  ``/metrics`` plus a request-counting / latency middleware.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("observability")

# --- Prometheus metrics (default registry) ---
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


def _route_label(request: Request) -> str:
    """Use the matched route template (e.g. /employees/{employee_id}) as the
    label to avoid unbounded cardinality from path parameters."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or request.url.path


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record request count + latency for every request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)
        start = time.perf_counter()
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            label = _route_label(request)
            REQUEST_LATENCY.labels(request.method, label).observe(time.perf_counter() - start)
            REQUEST_COUNT.labels(request.method, label, status).inc()


def metrics_endpoint() -> Response:
    """Render the Prometheus exposition format for scraping."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def setup_sentry() -> None:
    """Initialise Sentry if a DSN is configured and the SDK is available."""
    if not settings.SENTRY_DSN:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logger.warning("sentry_sdk_not_installed")
        return

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,  # never auto-capture request bodies / PII
    )
    logger.info("sentry_initialised", env=settings.APP_ENV)
