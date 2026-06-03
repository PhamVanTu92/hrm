"""One-shot bootstrap: seed RBAC + create default login accounts.

Idempotent — safe to run repeatedly. Run inside the app container/env::

    python -m scripts.bootstrap

Creates one account per role so you can log in and exercise RBAC immediately:

    admin    / <password>   (ADMIN    — full access)
    hr       / <password>   (HR       — employee/payroll/attendance/approval)
    manager  / <password>   (MANAGER  — read + approve)
    employee / <password>   (EMPLOYEE — self-service)

The password defaults to ``Admin@12345`` and can be overridden with the
``DEFAULT_PASSWORD`` env var. In production this script refuses to run unless
``BOOTSTRAP_FORCE=1`` is set (never ship default credentials).
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.modules.auth.models import Role, User
from scripts.seed import seed

# (username, role_code) for the default demo accounts.
DEFAULT_ACCOUNTS: list[tuple[str, str]] = [
    ("admin", "ADMIN"),
    ("hr", "HR"),
    ("manager", "MANAGER"),
    ("employee", "EMPLOYEE"),
]
DEFAULT_PASSWORD = os.environ.get("DEFAULT_PASSWORD", "Admin@12345")


async def bootstrap() -> None:
    # Always seed RBAC (safe + required in every environment).
    await seed()

    # In production, do NOT create default accounts unless explicitly forced.
    # Exit 0 (not an error) so the compose `bootstrap` service completes and the
    # api/worker that depend on it can start.
    if settings.is_production and os.environ.get("BOOTSTRAP_FORCE") != "1":
        print(
            "Production: bỏ qua tạo tài khoản mặc định (đặt BOOTSTRAP_FORCE=1 để ép). "
            "Tạo admin thật bằng: python -m scripts.create_superuser ..."
        )
        return

    # 2. Create the default accounts (idempotent).
    created: list[str] = []
    async with SessionLocal() as session:
        roles = {r.code: r for r in (await session.execute(select(Role))).scalars().all()}
        existing = {u.username for u in (await session.execute(select(User))).scalars().all()}
        for username, role_code in DEFAULT_ACCOUNTS:
            if username in existing:
                continue
            role = roles.get(role_code)
            if role is None:
                continue
            user = User(
                username=username,
                email=f"{username}@hrm.local",
                password_hash=hash_password(DEFAULT_PASSWORD),
                is_active=True,
            )
            user.roles.append(role)
            session.add(user)
            created.append(f"{username} ({role_code})")
        await session.commit()

    print("Bootstrap completed.")
    if created:
        print("Tài khoản đã tạo:")
        for c in created:
            print(f"  - {c}")
        print(f"Mật khẩu cho tất cả: {DEFAULT_PASSWORD}")
        print("⚠ Đổi mật khẩu ngay sau lần đăng nhập đầu (POST /api/v1/auth/change-password).")
    else:
        print("Tất cả tài khoản mặc định đã tồn tại — không tạo thêm.")


if __name__ == "__main__":
    asyncio.run(bootstrap())
