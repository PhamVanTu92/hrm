"""Async Redis client + small cache helpers.

Used for caching (RBAC resolution, master data), distributed locks, and as the
rate-limit backend. Celery uses its own broker/result connections.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis, from_url

from app.core.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    """Return a lazily-initialised shared async Redis client."""
    global _redis
    if _redis is None:
        _redis = from_url(
            str(settings.REDIS_URL),
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """Close the Redis connection pool on shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def cache_get_json(key: str) -> Any | None:
    """Get and JSON-decode a cached value, or ``None`` if missing."""
    raw = await get_redis().get(key)
    return json.loads(raw) if raw is not None else None


async def cache_set_json(key: str, value: Any, ttl_seconds: int) -> None:
    """JSON-encode and cache a value with TTL."""
    await get_redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)


async def cache_delete(*keys: str) -> None:
    """Delete one or more cache keys (for invalidation)."""
    if keys:
        await get_redis().delete(*keys)
