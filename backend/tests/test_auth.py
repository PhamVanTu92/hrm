"""Integration tests for the auth module (login, refresh, lockout, RBAC)."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from tests.conftest import API, create_user

PASSWORD = "S3cret!pass"


async def _make_user(session: AsyncSession, username: str = "alice") -> None:
    await create_user(session, username=username, password=PASSWORD, role_codes=["HR"])


# --------------------------------------------------------------------------- #
# Login                                                                       #
# --------------------------------------------------------------------------- #
async def test_login_success_returns_token_pair(seeded: AsyncSession, client: AsyncClient) -> None:
    await _make_user(seeded)
    resp = await client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.ACCESS_TOKEN_TTL_MIN * 60


async def test_login_wrong_password_401(seeded: AsyncSession, client: AsyncClient) -> None:
    await _make_user(seeded)
    resp = await client.post(f"{API}/auth/login", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_login_unknown_user_same_error_as_bad_password(
    seeded: AsyncSession, client: AsyncClient
) -> None:
    # Username enumeration protection: identical response for unknown user.
    resp = await client.post(
        f"{API}/auth/login", json={"username": "ghost", "password": "whatever"}
    )
    assert resp.status_code == 401


async def test_account_locks_after_max_attempts(seeded: AsyncSession, client: AsyncClient) -> None:
    await _make_user(seeded)
    for _ in range(settings.MAX_LOGIN_ATTEMPTS):
        r = await client.post(f"{API}/auth/login", json={"username": "alice", "password": "wrong"})
        assert r.status_code == 401
    # Even the correct password is now rejected with 423 Locked.
    locked = await client.post(
        f"{API}/auth/login", json={"username": "alice", "password": PASSWORD}
    )
    assert locked.status_code == 423
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"


# --------------------------------------------------------------------------- #
# /me                                                                         #
# --------------------------------------------------------------------------- #
async def test_me_returns_roles_and_permissions(seeded: AsyncSession, client: AsyncClient) -> None:
    await _make_user(seeded)
    login = await client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD})
    access = login.json()["access_token"]
    resp = await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["username"] == "alice"
    assert "HR" in data["roles"]
    assert "employee:write" in data["permissions"]


async def test_me_requires_token(client: AsyncClient) -> None:
    resp = await client.get(f"{API}/auth/me")
    assert resp.status_code == 401


async def test_invalid_token_rejected(client: AsyncClient) -> None:
    resp = await client.get(f"{API}/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Refresh rotation + reuse detection                                          #
# --------------------------------------------------------------------------- #
async def test_refresh_rotation_and_reuse_detection(
    seeded: AsyncSession, client: AsyncClient
) -> None:
    await _make_user(seeded)
    login = await client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD})
    r1 = login.json()["refresh_token"]

    # First rotation succeeds and yields a new refresh token.
    rot = await client.post(f"{API}/auth/refresh", json={"refresh_token": r1})
    assert rot.status_code == 200, rot.text
    r2 = rot.json()["refresh_token"]
    assert r2 != r1

    # Reusing the now-revoked r1 is detected as theft -> 401.
    reuse = await client.post(f"{API}/auth/refresh", json={"refresh_token": r1})
    assert reuse.status_code == 401

    # Reuse detection revokes the whole chain, so r2 is dead too.
    after = await client.post(f"{API}/auth/refresh", json={"refresh_token": r2})
    assert after.status_code == 401


# --------------------------------------------------------------------------- #
# Logout + change password                                                    #
# --------------------------------------------------------------------------- #
async def test_logout_revokes_refresh_token(seeded: AsyncSession, client: AsyncClient) -> None:
    await _make_user(seeded)
    login = await client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD})
    body = login.json()
    access, refresh = body["access_token"], body["refresh_token"]

    out = await client.post(
        f"{API}/auth/logout",
        json={"refresh_token": refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert out.status_code == 204
    # Revoked token can no longer be refreshed.
    assert (
        await client.post(f"{API}/auth/refresh", json={"refresh_token": refresh})
    ).status_code == 401


async def test_change_password_invalidates_old_credentials(
    seeded: AsyncSession, client: AsyncClient
) -> None:
    await _make_user(seeded)
    login = await client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD})
    access = login.json()["access_token"]

    changed = await client.post(
        f"{API}/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "BrandNew!pwd"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert changed.status_code == 204

    # Old password rejected, new password works.
    assert (
        await client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD})
    ).status_code == 401
    assert (
        await client.post(
            f"{API}/auth/login", json={"username": "alice", "password": "BrandNew!pwd"}
        )
    ).status_code == 200


async def test_change_password_wrong_current_rejected(
    seeded: AsyncSession, client: AsyncClient
) -> None:
    await _make_user(seeded)
    login = await client.post(f"{API}/auth/login", json={"username": "alice", "password": PASSWORD})
    access = login.json()["access_token"]
    resp = await client.post(
        f"{API}/auth/change-password",
        json={"current_password": "nope", "new_password": "BrandNew!pwd"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 422
