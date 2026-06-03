"""Microsoft Entra ID (Office 365 / Outlook) SSO — OIDC Authorization Code flow.

Flow:
1. ``/auth/sso/login`` -> redirect to Entra ``authorize`` (with anti-CSRF state).
2. User signs in with their Microsoft/Outlook account.
3. Entra redirects to ``/auth/sso/callback?code&state``.
4. We exchange the code for tokens, verify the ``id_token`` signature against
   Entra's JWKS, extract the identity, then provision/lookup a local user and
   issue our own JWT pair (same tokens as password login).

The ``id_token`` is verified (RS256 via JWKS, audience + issuer checked) — we
never trust unverified claims.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.logging import get_logger
from app.core.redis import get_redis

logger = get_logger("auth.sso")

_STATE_PREFIX = "sso:state:"
_STATE_TTL = 600  # 10 minutes
_SCOPE = "openid profile email"

# Cached JWKS client (fetches + caches Entra signing keys).
_jwks_client: jwt.PyJWKClient | None = None


@dataclass(frozen=True)
class MicrosoftClaims:
    """Verified identity from an Entra id_token."""

    external_id: str  # stable subject (Entra ``oid``)
    email: str
    name: str | None


def build_authorize_url(state: str) -> str:
    """Build the Entra authorization-endpoint URL to redirect the user to."""
    params = {
        "client_id": settings.MS_CLIENT_ID or "",
        "response_type": "code",
        "redirect_uri": settings.MS_REDIRECT_URI or "",
        "response_mode": "query",
        "scope": _SCOPE,
        "state": state,
    }
    return f"{settings.ms_authorize_url}?{urlencode(params)}"


async def create_state() -> str:
    """Generate + store a one-time anti-CSRF state token in Redis."""
    state = secrets.token_urlsafe(24)
    await get_redis().set(f"{_STATE_PREFIX}{state}", "1", ex=_STATE_TTL)
    return state


async def consume_state(state: str) -> bool:
    """Validate + delete a state token (single use). True if it was valid."""
    if not state:
        return False
    redis = get_redis()
    key = f"{_STATE_PREFIX}{state}"
    deleted = await redis.delete(key)
    return bool(deleted)


async def exchange_code(code: str) -> str:
    """Exchange an auth code for tokens; return the raw ``id_token``."""
    data = {
        "client_id": settings.MS_CLIENT_ID or "",
        "client_secret": settings.MS_CLIENT_SECRET or "",
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.MS_REDIRECT_URI or "",
        "scope": _SCOPE,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(settings.ms_token_url, data=data)
    if resp.status_code != 200:
        logger.warning("sso_token_exchange_failed", status=resp.status_code)
        raise AuthenticationError("Trao đổi mã SSO thất bại")
    id_token = resp.json().get("id_token")
    if not id_token:
        raise AuthenticationError("Phản hồi SSO thiếu id_token")
    return str(id_token)


def _client() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(settings.ms_jwks_uri)
    return _jwks_client


def verify_id_token(id_token: str) -> MicrosoftClaims:
    """Verify the id_token signature + claims and return the identity."""
    try:
        signing_key = _client().get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.MS_CLIENT_ID,
            issuer=settings.ms_issuer,
        )
    except jwt.PyJWTError as exc:
        logger.warning("sso_id_token_invalid", error=str(exc))
        raise AuthenticationError("id_token SSO không hợp lệ") from exc

    email = claims.get("email") or claims.get("preferred_username")
    external_id = claims.get("oid") or claims.get("sub")
    if not email or not external_id:
        raise AuthenticationError("Token SSO thiếu email hoặc định danh")
    return MicrosoftClaims(external_id=str(external_id), email=str(email), name=claims.get("name"))
