"""FastAPI application factory.

Wires middleware, exception handlers, rate limiting and the v1 API router.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import Response

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.observability import PrometheusMiddleware, metrics_endpoint, setup_sentry
from app.core.redis import close_redis, get_redis
from app.db.session import dispose_engines
from app.middleware.rate_limit import limiter
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.secure_headers import SecureHeadersMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup/shutdown hooks."""
    configure_logging()
    setup_sentry()
    logger.info("app_starting", env=settings.APP_ENV)
    yield
    await close_redis()
    await dispose_engines()
    logger.info("app_stopped")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ---- Rate limiting ----
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    # ---- CORS ----
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # ---- Custom middleware (outermost runs first) ----
    app.add_middleware(SecureHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(PrometheusMiddleware)

    # ---- Exception handlers ----
    register_exception_handlers(app)

    # ---- Routes ----
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Liveness + readiness probe (checks Redis)."""
        try:
            await get_redis().ping()
            redis_ok = "ok"
        except Exception:  # noqa: BLE001
            redis_ok = "down"
        return {"status": "ok", "redis": redis_ok, "env": settings.APP_ENV}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        """Prometheus scrape endpoint (restrict to the monitoring network)."""
        return metrics_endpoint()

    return app


def _rate_limit_handler(request, exc):  # type: ignore[no-untyped-def]
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMITED",
                "message": "Quá nhiều yêu cầu, vui lòng thử lại sau",
                "details": {},
            }
        },
    )


app = create_app()
