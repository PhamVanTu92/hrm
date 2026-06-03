"""Data-access for the auth module."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update

from app.db.repository import BaseRepository
from app.modules.auth.models import LoginAttempt, RefreshToken, User


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_with_roles(self, user_id: int) -> User | None:
        # roles + permissions are eager-loaded via lazy="selectin".
        stmt = select(User).where(User.id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def increment_failed(self, user: User) -> None:
        user.failed_attempts += 1
        await self.session.flush()

    async def reset_failed(self, user: User) -> None:
        user.failed_attempts = 0
        user.is_locked = False
        user.locked_until = None
        user.last_login_at = datetime.now(UTC)
        await self.session.flush()

    async def lock(self, user: User, until: datetime) -> None:
        user.is_locked = True
        user.locked_until = until
        await self.session.flush()


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def revoke(self, token: RefreshToken) -> None:
        token.revoked_at = datetime.now(UTC)
        await self.session.flush()

    async def revoke_all_for_user(self, user_id: int) -> None:
        """Revoke every active token for a user (used on reuse detection)."""
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await self.session.flush()


class LoginAttemptRepository(BaseRepository[LoginAttempt]):
    model = LoginAttempt

    async def record(self, *, username: str | None, ip: str | None, success: bool) -> None:
        self.session.add(LoginAttempt(username=username, ip=ip, success=success))
        await self.session.flush()
