"""Create an ADMIN superuser.

Usage::

    python -m scripts.create_superuser --username admin --password 'Str0ng!Pass'

Run scripts/seed.py first so the ADMIN role exists.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.modules.auth.models import Role, User


async def create(username: str, password: str, email: str | None) -> None:
    async with SessionLocal() as session:
        existing = await session.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            print(f"User '{username}' already exists.")
            return

        admin_role = (
            await session.execute(select(Role).where(Role.code == "ADMIN"))
        ).scalar_one_or_none()
        if admin_role is None:
            raise SystemExit("ADMIN role missing — run 'python -m scripts.seed' first.")

        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            is_active=True,
        )
        user.roles.append(admin_role)
        session.add(user)
        await session.commit()
        print(f"Superuser '{username}' created with ADMIN role.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--email", default=None)
    args = parser.parse_args()
    asyncio.run(create(args.username, args.password, args.email))


if __name__ == "__main__":
    main()
