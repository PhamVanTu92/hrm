"""Sensitive-data masking for audit payloads.

Audit logs must never store plaintext salary / national id / bank account, even
in the old/new value diff. Keys matching the sensitive set are replaced with a
fixed mask token.
"""

from __future__ import annotations

from typing import Any

SENSITIVE_KEYS: set[str] = {
    "password",
    "password_hash",
    "base_salary",
    "salary",
    "net_amount",
    "national_id",
    "cccd",
    "bank_account",
    "phone",
    "token",
    "refresh_token",
    "access_token",
}

MASK_TOKEN = "***"  # noqa: S105 - mask placeholder, not a secret


def mask(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a shallow copy with sensitive keys masked."""
    if not data:
        return data
    return {
        key: (MASK_TOKEN if key.lower() in SENSITIVE_KEYS else value) for key, value in data.items()
    }
