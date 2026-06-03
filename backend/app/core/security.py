"""Authentication primitives: password hashing and JWT tokens.

- Passwords: Argon2id (argon2-cffi) — resistant to GPU/ASIC cracking.
- Access tokens: short-lived JWT carrying roles + permissions for stateless
  authorization.
- Refresh tokens: opaque random strings; only their SHA-256 hash is stored in
  the DB so a DB leak cannot be replayed. Rotated on every refresh.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

_ph = PasswordHasher()  # Argon2id with OWASP-recommended defaults


# ---- Password hashing ----


def hash_password(plain: str) -> str:
    """Hash a plaintext password with Argon2id (salt embedded in output)."""
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its Argon2 hash. Never raises."""
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def needs_rehash(hashed: str) -> bool:
    """Return True if the hash should be upgraded (params changed)."""
    try:
        return _ph.check_needs_rehash(hashed)
    except Exception:
        return False


# ---- JWT access tokens ----


def create_access_token(
    *,
    subject: str | int,
    roles: list[str],
    permissions: list[str],
    extra: dict[str, Any] | None = None,
) -> str:
    """Create a signed short-lived access token.

    Args:
        subject: user id (``sub`` claim).
        roles: role codes carried for convenience/UI.
        permissions: flattened permission codes used for authorization.
        extra: optional extra claims (e.g. employee_id, department_id).
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "roles": roles,
        "perms": permissions,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate an access token. Raises ``jwt.PyJWTError`` on failure."""
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "sub", "typ"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return payload


# ---- Refresh tokens (opaque) ----


def generate_refresh_token() -> str:
    """Generate a cryptographically strong opaque refresh token."""
    return secrets.token_urlsafe(48)


def hash_token(raw: str) -> str:
    """Hash an opaque token for at-rest storage (SHA-256 hex)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def refresh_expiry() -> datetime:
    """Compute the absolute expiry for a new refresh token."""
    return datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)
