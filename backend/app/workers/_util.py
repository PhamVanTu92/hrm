"""Helpers for running async DB work inside synchronous Celery tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


def run_async(coro: Awaitable[T]) -> T:
    """Run a coroutine to completion from a sync Celery worker.

    Each task gets its own event loop; the async engine's connections are
    created lazily inside the loop. Suitable for low/medium task volumes. For
    very high throughput, run a dedicated async worker pool instead.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
