"""initial schema: auth/rbac, org/employee, dynamic profile, immutable audit

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- Extensions ----
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")

    # ---- RBAC ----
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
    )
    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id",
            sa.BigInteger,
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "permission_id",
            sa.BigInteger,
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_locked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("failed_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            sa.BigInteger,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "role_id",
            sa.BigInteger,
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.BigInteger, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("ip", pg.INET, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_refresh_user", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_hash", "refresh_tokens", ["token_hash"])
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(100), nullable=True),
        sa.Column("ip", pg.INET, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_login_username", "login_attempts", ["username"])
    op.create_index("ix_login_created", "login_attempts", ["created_at"])

    # ---- Org & Employee ----
    op.create_table(
        "departments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("parent_id", sa.BigInteger, sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("manager_id", sa.BigInteger, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
    )
    op.create_table(
        "employees",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("employee_code", sa.String(50), nullable=False, unique=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.id"), nullable=True, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("department_id", sa.BigInteger, sa.ForeignKey("departments.id"), nullable=True),
        sa.Column("position_id", sa.BigInteger, sa.ForeignKey("positions.id"), nullable=True),
        sa.Column("manager_id", sa.BigInteger, sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("join_date", sa.Date, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("enc_national_id", sa.LargeBinary, nullable=True),
        sa.Column("enc_phone", sa.LargeBinary, nullable=True),
        sa.Column("enc_bank_account", sa.LargeBinary, nullable=True),
        sa.Column("enc_base_salary", sa.LargeBinary, nullable=True),
        sa.Column("national_id_bidx", sa.String(64), nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger, nullable=True),
        sa.Column("updated_by", sa.BigInteger, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_emp_dept", "employees", ["department_id"])
    op.create_index("ix_emp_manager", "employees", ["manager_id"])
    op.create_index("ix_emp_nid_bidx", "employees", ["national_id_bidx"])
    # trigram index for name search
    op.execute("CREATE INDEX ix_emp_name_trgm ON employees USING gin (full_name gin_trgm_ops)")

    # ---- Dynamic profile ----
    op.create_table(
        "profile_categories",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "profile_fields",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "category_id", sa.BigInteger, sa.ForeignKey("profile_categories.id"), nullable=False
        ),
        sa.Column("field_key", sa.String(80), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("data_type", sa.String(20), nullable=False),
        sa.Column("options", pg.JSONB, nullable=True),
        sa.Column("is_required", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_encrypted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("validation", pg.JSONB, nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("category_id", "field_key", name="uq_field_key"),
    )
    op.create_table(
        "employee_dynamic_profiles",
        sa.Column(
            "employee_id",
            sa.BigInteger,
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("data", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute(
        "CREATE INDEX ix_dyn_profile_gin ON employee_dynamic_profiles "
        "USING gin (data jsonb_path_ops)"
    )

    # ---- Immutable, partitioned audit log ----
    op.execute(
        """
        CREATE TABLE audit_logs (
            id          BIGINT GENERATED ALWAYS AS IDENTITY,
            actor_id    BIGINT,
            action      VARCHAR(20) NOT NULL,
            entity      VARCHAR(60) NOT NULL,
            entity_id   VARCHAR(60),
            old_value   JSONB,
            new_value   JSONB,
            ip          INET,
            user_agent  TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
        """
    )
    op.execute("CREATE INDEX ix_audit_entity ON audit_logs (entity, entity_id, created_at DESC)")
    # Default catch-all partition + current month partition. A scheduled job
    # creates the next month partition (see workers/cron).
    op.execute("CREATE TABLE audit_logs_default PARTITION OF audit_logs DEFAULT")
    op.execute(
        "CREATE TABLE audit_logs_2026_05 PARTITION OF audit_logs "
        "FOR VALUES FROM ('2026-05-01') TO ('2026-06-01')"
    )
    # Immutability: reject UPDATE/DELETE at the DB level.
    op.execute("CREATE RULE audit_no_update AS ON UPDATE TO audit_logs DO INSTEAD NOTHING")
    op.execute("CREATE RULE audit_no_delete AS ON DELETE TO audit_logs DO INSTEAD NOTHING")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
    op.drop_table("employee_dynamic_profiles")
    op.drop_table("profile_fields")
    op.drop_table("profile_categories")
    op.drop_table("employees")
    op.drop_table("positions")
    op.drop_table("departments")
    op.drop_table("login_attempts")
    op.drop_table("refresh_tokens")
    op.drop_table("user_roles")
    op.drop_table("users")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
