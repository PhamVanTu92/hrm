"""Structured logging via structlog.

Emits JSON logs in production (machine-parseable for Loki/ELK) and pretty
console logs in development. A ``request_id`` is bound per-request by the
RequestContextMiddleware so all logs of one request correlate.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import settings

_configured = False


def configure_logging() -> None:
    """Configure stdlib logging + structlog once at startup."""
    global _configured
    if _configured:
        return

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.LOG_LEVEL,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.LOG_JSON:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.LOG_LEVEL)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)


def bind_request_context(**kwargs: Any) -> None:
    """Bind key/values (e.g. request_id, user_id) to the current context."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_request_context() -> None:
    """Clear bound context vars (call at end of request)."""
    structlog.contextvars.clear_contextvars()
