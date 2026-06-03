"""SlowAPI rate limiter backed by Redis (works across multiple app instances)."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=str(settings.RATE_LIMIT_REDIS_URL),
    default_limits=["300/minute"],
    headers_enabled=True,
)
