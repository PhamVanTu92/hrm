"""Tests for the production secrets guard in app.core.config.Settings."""

from __future__ import annotations

import secrets

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_DB = "postgresql+asyncpg://u:p@localhost:5432/d"


def _strong_keys() -> dict[str, str]:
    return {"AES_KEY_HEX": secrets.token_hex(32), "BLIND_INDEX_KEY_HEX": secrets.token_hex(32)}


def test_production_rejects_placeholder_jwt() -> None:
    with pytest.raises(ValidationError):
        Settings(
            APP_ENV="production",
            DATABASE_URL=_DB,
            JWT_SECRET_KEY="change-me-to-a-long-random-secret-min-32",
            **_strong_keys(),
        )


def test_production_rejects_repeated_char_aes_key() -> None:
    with pytest.raises(ValidationError):
        Settings(
            APP_ENV="production",
            DATABASE_URL=_DB,
            JWT_SECRET_KEY=secrets.token_urlsafe(40),
            AES_KEY_HEX="0" * 64,
            BLIND_INDEX_KEY_HEX="1" * 64,
        )


def test_production_rejects_key_reuse() -> None:
    same = secrets.token_hex(32)
    with pytest.raises(ValidationError):
        Settings(
            APP_ENV="production",
            DATABASE_URL=_DB,
            JWT_SECRET_KEY=secrets.token_urlsafe(40),
            AES_KEY_HEX=same,
            BLIND_INDEX_KEY_HEX=same,
        )


def test_production_accepts_strong_secrets() -> None:
    cfg = Settings(
        APP_ENV="production",
        DEBUG=False,
        DATABASE_URL=_DB,
        JWT_SECRET_KEY=secrets.token_urlsafe(40),
        **_strong_keys(),
    )
    assert cfg.is_production is True


def test_development_skips_guard() -> None:
    # Weak keys are fine outside production (local dev convenience).
    cfg = Settings(
        APP_ENV="development",
        DATABASE_URL=_DB,
        JWT_SECRET_KEY="change-me-please-32-characters-long-xx",
        AES_KEY_HEX="0" * 64,
        BLIND_INDEX_KEY_HEX="0" * 64,
    )
    assert cfg.is_production is False
