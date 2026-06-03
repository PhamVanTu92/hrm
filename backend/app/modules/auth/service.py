"""Auth use-cases: login, refresh (rotation), logout, change password.

Implements anti-bruteforce account locking and refresh-token rotation with
reuse detection.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AccountLocked, AuthenticationError, ValidationError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    needs_rehash,
    refresh_expiry,
    verify_password,
)
from app.modules.auth.models import RefreshToken, Role, User
from app.modules.auth.repository import (
    LoginAttemptRepository,
    RefreshTokenRepository,
    UserRepository,
)
from app.modules.auth.schemas import TokenResponse
from app.modules.auth.sso import MicrosoftClaims

logger = get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.attempts = LoginAttemptRepository(session)

    # ---- login ----

    async def login(
        self, *, username: str, password: str, ip: str | None, user_agent: str | None
    ) -> TokenResponse:
        user = await self.users.get_by_username(username)

        if user is None:
            await self.attempts.record(username=username, ip=ip, success=False)
            # Same error as bad password to avoid username enumeration.
            raise AuthenticationError("Sai tài khoản hoặc mật khẩu")

        self._assert_not_locked(user)

        if not user.is_active:
            raise AuthenticationError("Tài khoản đã bị vô hiệu hóa")

        if not verify_password(password, user.password_hash):
            await self._handle_failed_login(user, ip)
            raise AuthenticationError("Sai tài khoản hoặc mật khẩu")

        # Transparent hash upgrade if Argon2 params changed.
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        await self.users.reset_failed(user)
        await self.attempts.record(username=username, ip=ip, success=True)
        return await self._issue_tokens(user, ip=ip, user_agent=user_agent)

    def _assert_not_locked(self, user: User) -> None:
        if user.is_locked and user.locked_until and user.locked_until > datetime.now(UTC):
            raise AccountLocked(
                f"Tài khoản bị khóa tới {user.locked_until.isoformat()}",
                details={"locked_until": user.locked_until.isoformat()},
            )

    async def _handle_failed_login(self, user: User, ip: str | None) -> None:
        await self.users.increment_failed(user)
        await self.attempts.record(username=user.username, ip=ip, success=False)
        if user.failed_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            until = datetime.now(UTC) + timedelta(minutes=settings.ACCOUNT_LOCK_MINUTES)
            await self.users.lock(user, until)
            logger.warning("account_locked", user_id=user.id, until=until.isoformat())

    # ---- SSO (Microsoft Entra ID) ----

    async def sso_login(
        self, claims: MicrosoftClaims, *, ip: str | None, user_agent: str | None
    ) -> TokenResponse:
        """Log in (or provision) a user from verified Microsoft claims."""
        user = await self._find_sso_user(claims)
        if user is None:
            if not settings.SSO_AUTO_PROVISION:
                raise AuthenticationError("Tài khoản chưa được cấp quyền truy cập")
            user = await self._provision_sso_user(claims)

        if not user.is_active:
            raise AuthenticationError("Tài khoản đã bị vô hiệu hóa")

        # Keep the external link fresh (first login after manual creation).
        user.auth_provider = "MICROSOFT"
        user.external_id = claims.external_id
        await self.users.reset_failed(user)
        return await self._issue_tokens(user, ip=ip, user_agent=user_agent)

    async def _find_sso_user(self, claims: MicrosoftClaims) -> User | None:
        stmt = select(User).where(
            (User.external_id == claims.external_id) | (User.email == claims.email)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _provision_sso_user(self, claims: MicrosoftClaims) -> User:
        role = (
            await self.session.execute(select(Role).where(Role.code == settings.SSO_DEFAULT_ROLE))
        ).scalar_one_or_none()
        user = User(
            username=claims.email,
            email=claims.email,
            # Unusable password: SSO users authenticate via Microsoft only.
            password_hash=hash_password(secrets.token_urlsafe(32)),
            is_active=True,
            auth_provider="MICROSOFT",
            external_id=claims.external_id,
        )
        if role is not None:
            user.roles.append(role)
        self.session.add(user)
        await self.session.flush()
        logger.info("sso_user_provisioned", email=claims.email, role=settings.SSO_DEFAULT_ROLE)
        return user

    # ---- token issuance ----

    async def _issue_tokens(
        self, user: User, *, ip: str | None, user_agent: str | None
    ) -> TokenResponse:
        access = create_access_token(
            subject=user.id,
            roles=user.role_codes,
            permissions=sorted(user.permission_codes),
        )
        raw_refresh = generate_refresh_token()
        await self.tokens.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_token(raw_refresh),
                expires_at=refresh_expiry(),
                user_agent=user_agent,
                ip=ip,
            )
        )
        return TokenResponse(
            access_token=access,
            refresh_token=raw_refresh,
            expires_in=settings.ACCESS_TOKEN_TTL_MIN * 60,
        )

    # ---- refresh with rotation ----

    async def refresh(
        self, *, raw_refresh: str, ip: str | None, user_agent: str | None
    ) -> TokenResponse:
        stored = await self.tokens.get_by_hash(hash_token(raw_refresh))
        if stored is None:
            raise AuthenticationError("Refresh token không hợp lệ")

        if stored.revoked_at is not None:
            # Reuse of a revoked token => likely theft. Revoke everything.
            await self.tokens.revoke_all_for_user(stored.user_id)
            logger.warning("refresh_token_reuse_detected", user_id=stored.user_id)
            raise AuthenticationError("Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại")

        if not stored.is_active:
            raise AuthenticationError("Refresh token đã hết hạn")

        user = await self.users.get_by_id_with_roles(stored.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Tài khoản không khả dụng")

        # Rotate: revoke old, issue new pair.
        await self.tokens.revoke(stored)
        return await self._issue_tokens(user, ip=ip, user_agent=user_agent)

    # ---- logout ----

    async def logout(self, *, raw_refresh: str) -> None:
        stored = await self.tokens.get_by_hash(hash_token(raw_refresh))
        if stored is not None and stored.revoked_at is None:
            await self.tokens.revoke(stored)

    # ---- change password ----

    async def change_password(
        self, *, user_id: int, current_password: str, new_password: str
    ) -> None:
        user = await self.users.get_by_id_with_roles(user_id)
        if user is None:
            raise AuthenticationError("Người dùng không tồn tại")
        if not verify_password(current_password, user.password_hash):
            raise ValidationError("Mật khẩu hiện tại không đúng")
        user.password_hash = hash_password(new_password)
        await self.session.flush()
        # Invalidate all sessions after password change.
        await self.tokens.revoke_all_for_user(user_id)
