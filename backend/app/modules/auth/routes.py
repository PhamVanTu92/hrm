"""Auth API routes: /auth/login, /refresh, /logout, /me, /change-password."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.pagination import Envelope
from app.core.rbac import CurrentUserDep, get_current_user
from app.db.session import get_db
from app.middleware.rate_limit import limiter
from app.modules.auth import sso
from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest, db: DbDep) -> TokenResponse:
    """Authenticate and return an access + refresh token pair."""
    return await AuthService(db).login(
        username=payload.username,
        password=payload.password,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(request: Request, payload: RefreshRequest, db: DbDep) -> TokenResponse:
    """Rotate a refresh token, returning a fresh token pair."""
    return await AuthService(db).refresh(
        raw_refresh=payload.refresh_token,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest, db: DbDep, _: CurrentUserDep) -> None:
    """Revoke the supplied refresh token."""
    await AuthService(db).logout(raw_refresh=payload.refresh_token)


@router.get("/me", response_model=Envelope[MeResponse])
async def me(user: Annotated[object, Depends(get_current_user)], db: DbDep) -> Envelope[MeResponse]:
    """Return the current user's profile, roles and permissions."""
    db_user = await UserRepository(db).get_by_id_with_roles(user.id)  # type: ignore[attr-defined]
    assert db_user is not None
    return Envelope(
        data=MeResponse(
            id=db_user.id,
            username=db_user.username,
            email=db_user.email,
            roles=db_user.role_codes,
            permissions=sorted(db_user.permission_codes),
        )
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(payload: ChangePasswordRequest, db: DbDep, user: CurrentUserDep) -> None:
    """Change the current user's password and revoke all sessions."""
    await AuthService(db).change_password(
        user_id=user.id,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )


# --------------------------------------------------------------------------- #
# Microsoft Entra ID SSO                                                       #
# --------------------------------------------------------------------------- #
def _require_sso_enabled() -> None:
    if not settings.SSO_ENABLED:
        raise AuthenticationError("SSO chưa được bật")


@router.get("/sso/login")
async def sso_login() -> RedirectResponse:
    """Redirect the browser to Microsoft to start the OIDC login."""
    _require_sso_enabled()
    state = await sso.create_state()
    return RedirectResponse(sso.build_authorize_url(state))


@router.get("/sso/callback")
async def sso_callback(
    request: Request,
    db: DbDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Handle the Entra redirect: verify, provision/lookup, issue tokens.

    On success redirects to the frontend with tokens in the URL fragment
    (fragments are not sent to servers/logged), where the SPA stores them.
    """
    _require_sso_enabled()
    if error or not code:
        raise AuthenticationError(f"SSO bị hủy hoặc lỗi: {error or 'thiếu code'}")
    if not await sso.consume_state(state or ""):
        raise AuthenticationError("State SSO không hợp lệ hoặc đã hết hạn")

    id_token = await sso.exchange_code(code)
    claims = sso.verify_id_token(id_token)
    tokens = await AuthService(db).sso_login(
        claims,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    fragment = (
        f"access_token={tokens.access_token}"
        f"&refresh_token={tokens.refresh_token}"
        f"&expires_in={tokens.expires_in}"
    )
    return RedirectResponse(f"{settings.SSO_FRONTEND_REDIRECT}#{fragment}")
