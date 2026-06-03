"""Seed roles, permissions and the default role->permission mapping.

Idempotent: safe to run repeatedly. Run inside the app container::

    python -m scripts.seed
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.rbac import PERMISSIONS, ROLE_PERMISSIONS
from app.db.session import SessionLocal
from app.modules.auth.models import Permission, Role, RolePermission

ROLE_NAMES = {
    "ADMIN": "Quản trị hệ thống",
    "HR": "Nhân sự",
    "MANAGER": "Quản lý",
    "EMPLOYEE": "Nhân viên",
}


async def seed() -> None:
    async with SessionLocal() as session:
        # Permissions
        existing_perms = {
            p.code: p for p in (await session.execute(select(Permission))).scalars().all()
        }
        for code in sorted(PERMISSIONS):
            if code not in existing_perms:
                perm = Permission(code=code, name=code)
                session.add(perm)
                existing_perms[code] = perm
        await session.flush()

        # Roles
        existing_roles = {r.code: r for r in (await session.execute(select(Role))).scalars().all()}
        for code, name in ROLE_NAMES.items():
            if code not in existing_roles:
                role = Role(code=code, name=name, is_system=True)
                session.add(role)
                existing_roles[code] = role
        await session.flush()

        # Role -> permission links
        existing_links = {
            (rp.role_id, rp.permission_id)
            for rp in (await session.execute(select(RolePermission))).scalars().all()
        }
        for role_code, perm_codes in ROLE_PERMISSIONS.items():
            role = existing_roles[role_code]
            for perm_code in perm_codes:
                perm = existing_perms[perm_code]
                if (role.id, perm.id) not in existing_links:
                    session.add(RolePermission(role_id=role.id, permission_id=perm.id))

        await session.commit()
        print("Seed completed: permissions, roles, role_permissions.")


if __name__ == "__main__":
    asyncio.run(seed())
