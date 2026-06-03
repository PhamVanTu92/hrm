"""Tests for Microsoft SSO: authorize-URL build + provisioning/login service."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import decode_access_token
from app.modules.auth.service import AuthService
from app.modules.auth.sso import MicrosoftClaims, build_authorize_url

CLAIMS = MicrosoftClaims(external_id="oid-abc-123", email="alice@congty.vn", name="Alice")


def test_build_authorize_url() -> None:
    url = build_authorize_url("state-xyz")
    assert "oauth2/v2.0/authorize" in url
    assert "response_type=code" in url
    assert "state=state-xyz" in url
    assert "scope=openid" in url  # url-encoded "openid profile email"


async def test_sso_provisions_new_user(seeded: AsyncSession) -> None:
    svc = AuthService(seeded)
    tokens = await svc.sso_login(CLAIMS, ip=None, user_agent=None)

    payload = decode_access_token(tokens.access_token)
    assert payload["sub"]
    assert settings.SSO_DEFAULT_ROLE in payload["roles"]  # EMPLOYEE by default

    user = await svc.users.get_by_username("alice@congty.vn")
    assert user is not None
    assert user.auth_provider == "MICROSOFT"
    assert user.external_id == "oid-abc-123"


async def test_sso_second_login_reuses_user(seeded: AsyncSession) -> None:
    svc = AuthService(seeded)
    await svc.sso_login(CLAIMS, ip=None, user_agent=None)
    await svc.sso_login(CLAIMS, ip=None, user_agent=None)

    # No duplicate user created for the same external identity.
    from sqlalchemy import func, select

    from app.modules.auth.models import User

    count = (
        await seeded.execute(
            select(func.count()).select_from(User).where(User.email == "alice@congty.vn")
        )
    ).scalar_one()
    assert count == 1


async def test_sso_no_autoprovision_rejects(
    seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "SSO_AUTO_PROVISION", False)
    svc = AuthService(seeded)
    with pytest.raises(AuthenticationError):
        await svc.sso_login(
            MicrosoftClaims(external_id="oid-new", email="bob@congty.vn", name="Bob"),
            ip=None,
            user_agent=None,
        )
