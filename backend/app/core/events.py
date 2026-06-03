"""Lightweight in-process domain event bus.

Modules communicate through events instead of importing each other's internals
(e.g. ``LeaveApproved`` triggers attendance compensation). Handlers may run the
side-effect inline or enqueue a Celery task. This keeps a Modular Monolith
decoupled without the operational cost of Kafka.
"""

from __future__ import annotations

import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.core.logging import get_logger

logger = get_logger(__name__)

TEvent = TypeVar("TEvent")
Handler = Callable[[Any], Awaitable[None] | None]

_handlers: dict[type, list[Handler]] = defaultdict(list)


def subscribe(event_type: type[TEvent]) -> Callable[[Handler], Handler]:
    """Decorator registering a handler for an event type."""

    def decorator(fn: Handler) -> Handler:
        _handlers[event_type].append(fn)
        return fn

    return decorator


async def publish(event: object) -> None:
    """Dispatch an event to all subscribed handlers.

    A failing non-critical handler is logged but does not abort the publisher.
    Critical side-effects (e.g. audit) should be written in the same DB
    transaction by the caller, not via this bus.
    """
    for handler in _handlers[type(event)]:
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001
            logger.exception(
                "event_handler_failed",
                event_type=type(event).__name__,
                handler=getattr(handler, "__name__", repr(handler)),
            )
