"""sso: add auth_provider + external_id to users

Revision ID: 0006_sso
Revises: 0005_payslip
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_sso"
down_revision: str | None = "0005_payslip"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_provider", sa.String(20), nullable=False, server_default="LOCAL"),
    )
    op.add_column("users", sa.Column("external_id", sa.String(64), nullable=True))
    op.create_index("ix_users_external_id", "users", ["external_id"])


def downgrade() -> None:
    op.drop_index("ix_users_external_id", table_name="users")
    op.drop_column("users", "external_id")
    op.drop_column("users", "auth_provider")
