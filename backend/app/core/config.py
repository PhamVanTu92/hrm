"""Application configuration.

All runtime configuration is read from environment variables and validated
through Pydantic Settings. Nothing secret is hard-coded; production injects
secrets via Docker secrets / Vault.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Loaded once and cached via :func:`get_settings`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Read secrets from files (Docker secrets / Vault Agent) when SECRETS_DIR
        # is set, e.g. /run/secrets/jwt_secret_key. Env vars still take priority.
        secrets_dir=os.environ.get("SECRETS_DIR") or None,
    )

    # ---- App ----
    APP_NAME: str = "HRM Backend"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # ---- Database ----
    DATABASE_URL: PostgresDsn
    # Optional read replica for read-heavy queries (falls back to primary).
    DATABASE_REPLICA_URL: PostgresDsn | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False

    # ---- Redis / Celery ----
    # Defaults are validated/coerced to RedisDsn by pydantic at runtime; the
    # str literal trips mypy's strict assignment check, hence the ignores.
    REDIS_URL: RedisDsn = Field(default="redis://localhost:6379/0")  # type: ignore[assignment]
    CELERY_BROKER_URL: RedisDsn = Field(default="redis://localhost:6379/2")  # type: ignore[assignment]
    CELERY_RESULT_BACKEND: RedisDsn = Field(default="redis://localhost:6379/3")  # type: ignore[assignment]
    RATE_LIMIT_REDIS_URL: RedisDsn = Field(default="redis://localhost:6379/1")  # type: ignore[assignment]

    # ---- Security: JWT ----
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MIN: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 7

    # ---- Security: AES-256 ----
    # 32-byte key encoded as 64 hex chars => AES-256.
    AES_KEY_HEX: str = Field(min_length=64, max_length=64)
    # HMAC key (hex) for blind-index of searchable encrypted fields.
    BLIND_INDEX_KEY_HEX: str = Field(min_length=64, max_length=64)

    # ---- Anti-bruteforce ----
    MAX_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCK_MINUTES: int = 15
    LOGIN_RATE_LIMIT: str = "10/minute"

    # ---- CORS ----
    # NoDecode: take the raw env string (e.g. "https://a.com,https://b.com") and
    # let _split_cors handle it, instead of pydantic-settings trying json.loads.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # ---- Storage (S3 / MinIO) ----
    S3_ENDPOINT: str | None = None
    S3_BUCKET: str = "hrm"
    S3_ACCESS_KEY: str | None = None
    S3_SECRET_KEY: str | None = None

    # ---- Email (SMTP) ----
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "hrm@company.vn"
    SMTP_USE_TLS: bool = True  # STARTTLS on a plaintext port (587)
    SMTP_USE_SSL: bool = False  # implicit TLS (port 465)
    SMTP_TIMEOUT: int = 30

    # ---- SSO: Microsoft Entra ID (Office 365 / Outlook) ----
    SSO_ENABLED: bool = False
    MS_TENANT_ID: str | None = None
    MS_CLIENT_ID: str | None = None
    MS_CLIENT_SECRET: str | None = None
    # Where Entra redirects back (must match the app registration), e.g.
    # https://hrm.congty.vn/api/v1/auth/sso/callback
    MS_REDIRECT_URI: str | None = None
    # Auto-create a local user on first SSO login + the role they get.
    SSO_AUTO_PROVISION: bool = True
    SSO_DEFAULT_ROLE: str = "EMPLOYEE"
    # Frontend page that receives the issued tokens after callback.
    SSO_FRONTEND_REDIRECT: str = "http://localhost:3000/sso/callback"

    # ---- Observability ----
    SENTRY_DSN: str | None = None
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # ---- Localization ----
    TIMEZONE: str = "Asia/Ho_Chi_Minh"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, v: str | list[str]) -> list[str]:
        """Allow comma-separated origins from a single env var."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _guard_production_secrets(self) -> Settings:
        """Refuse to boot in production with placeholder/weak secrets.

        Catches the most common deploy mistake — shipping the sample keys from
        ``.env.example``. Only enforced when ``APP_ENV=production``.
        """
        if self.APP_ENV != "production":
            return self

        problems: list[str] = []
        if self.DEBUG:
            problems.append("DEBUG phải tắt ở production")
        if "change" in self.JWT_SECRET_KEY.lower():
            problems.append("JWT_SECRET_KEY còn là giá trị mẫu")
        for name, value in (
            ("AES_KEY_HEX", self.AES_KEY_HEX),
            ("BLIND_INDEX_KEY_HEX", self.BLIND_INDEX_KEY_HEX),
        ):
            # Reject single-repeated-character placeholders like "0000..." / "aaaa...".
            if value == value[0] * len(value):
                problems.append(f"{name} là key mẫu (ký tự lặp)")
        if self.AES_KEY_HEX == self.BLIND_INDEX_KEY_HEX:
            problems.append("AES_KEY_HEX và BLIND_INDEX_KEY_HEX không được trùng nhau")

        if problems:
            raise ValueError("Cấu hình production không an toàn: " + "; ".join(problems))
        return self

    @property
    def aes_key(self) -> bytes:
        """Raw 32-byte AES key."""
        return bytes.fromhex(self.AES_KEY_HEX)

    @property
    def blind_index_key(self) -> bytes:
        """Raw HMAC key for blind index."""
        return bytes.fromhex(self.BLIND_INDEX_KEY_HEX)

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    # ---- Microsoft Entra ID endpoints (v2.0, single tenant) ----
    @property
    def ms_authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.MS_TENANT_ID}"

    @property
    def ms_authorize_url(self) -> str:
        return f"{self.ms_authority}/oauth2/v2.0/authorize"

    @property
    def ms_token_url(self) -> str:
        return f"{self.ms_authority}/oauth2/v2.0/token"

    @property
    def ms_jwks_uri(self) -> str:
        return f"{self.ms_authority}/discovery/v2.0/keys"

    @property
    def ms_issuer(self) -> str:
        return f"https://login.microsoftonline.com/{self.MS_TENANT_ID}/v2.0"

    @property
    def sync_database_url(self) -> str:
        """Sync DSN for Alembic (psycopg)."""
        return (
            str(self.DATABASE_URL)
            .replace("+asyncpg", "")
            .replace("postgresql://", "postgresql+psycopg://")
        )


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton."""
    return Settings()


settings = get_settings()
