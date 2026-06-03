"""RBAC: permission catalog + FastAPI authorization dependencies.

Authorization is enforced at the API layer. The access token carries the
flattened permission set, so the common case (static permission check) needs no
DB round-trip. Object-level checks (e.g. manager can only see own department)
are done inside services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import AuthenticationError, PermissionDenied
from app.core.security import decode_access_token

# ---- Permission catalog (single source of truth) ----

PERMISSIONS: set[str] = {
    # auth / user
    "user:read",
    "user:manage",
    "role:manage",
    # employee
    "employee:read",
    "employee:read_all",
    "employee:write",
    "salary:view_sensitive",  # decrypt salary/CCCD/bank — always audited
    # dynamic fields
    "dynamic_field:manage",
    # attendance
    "attendance:read",
    "attendance:manage",
    # approval
    "approval:act",  # approve/reject a step you are assigned
    "approval:manage",  # configure workflows + view all instances
    # payroll
    "payroll:read",
    "payroll:run",
    "payroll:lock",
    # audit
    "audit:read",
}

# Default role -> permission mapping used by the seed script.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "ADMIN": set(PERMISSIONS),
    "HR": {
        "user:read",
        "employee:read",
        "employee:read_all",
        "employee:write",
        "salary:view_sensitive",
        "dynamic_field:manage",
        "attendance:read",
        "attendance:manage",
        "approval:act",
        "approval:manage",
        "payroll:read",
        "payroll:run",
        "payroll:lock",
    },
    "MANAGER": {
        "employee:read",
        "attendance:read",
        "approval:act",
    },
    "EMPLOYEE": {
        "employee:read",
        "attendance:read",
    },
}


@dataclass
class CurrentUser:
    """Authenticated principal derived from the access token."""

    id: int
    roles: list[str] = field(default_factory=list)
    perms: set[str] = field(default_factory=set)
    employee_id: int | None = None
    department_id: int | None = None

    def has(self, *needed: str) -> bool:
        return set(needed).issubset(self.perms)


_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    """Decode the bearer access token into a :class:`CurrentUser`."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Thiếu access token")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token đã hết hạn") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Access token không hợp lệ") from exc

    user = CurrentUser(
        id=int(payload["sub"]),
        roles=list(payload.get("roles", [])),
        perms=set(payload.get("perms", [])),
        employee_id=payload.get("employee_id"),
        department_id=payload.get("department_id"),
    )
    # Expose to logging/audit middleware.
    request.state.user_id = user.id
    return user


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_perm(*needed: str) -> Any:
    """Return a dependency that requires all listed permissions.

    Typed as ``Any`` so it can be used directly as a parameter default whose
    annotation is :class:`CurrentUser`::

        async def route(user: CurrentUser = require_perm("payroll:read")): ...
    """

    async def checker(user: CurrentUserDep) -> CurrentUser:
        if not user.has(*needed):
            raise PermissionDenied(
                "Bạn không có quyền thực hiện thao tác này",
                details={"required": list(needed)},
            )
        return user

    return Depends(checker)
