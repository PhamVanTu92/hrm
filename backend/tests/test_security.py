"""Unit tests for encryption + security primitives (no DB / no network)."""

from __future__ import annotations

from decimal import Decimal

import jwt
import pytest

from app.core.encryption import (
    blind_index,
    decrypt,
    decrypt_decimal,
    decrypt_from_json,
    decrypt_optional,
    encrypt,
    encrypt_decimal,
    encrypt_for_json,
    encrypt_optional,
    is_encrypted_json,
)
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)


# --------------------------------------------------------------------------- #
# AES-256-GCM field encryption                                                #
# --------------------------------------------------------------------------- #
def test_encrypt_decrypt_roundtrip() -> None:
    secret = "012345678901"
    blob = encrypt(secret)
    assert isinstance(blob, bytes)
    assert blob[:1] == b"\x01"  # version prefix
    assert decrypt(blob) == secret


def test_encrypt_uses_random_nonce() -> None:
    # Same plaintext must produce different ciphertext (semantic security).
    assert encrypt("same") != encrypt("same")


def test_decrypt_rejects_tampered_ciphertext() -> None:
    blob = bytearray(encrypt("sensitive"))
    blob[-1] ^= 0xFF  # flip a bit in the GCM tag
    with pytest.raises(Exception):  # noqa: B017,PT011 - InvalidTag
        decrypt(bytes(blob))


def test_decrypt_unknown_version_raises() -> None:
    blob = bytearray(encrypt("x"))
    blob[0] = 99
    with pytest.raises(ValueError, match="Unknown AES key version"):
        decrypt(bytes(blob))


def test_encrypt_optional_passthrough_none_and_empty() -> None:
    assert encrypt_optional(None) is None
    assert encrypt_optional("") is None
    assert decrypt_optional(None) is None
    blob = encrypt_optional("0901234567")
    assert blob is not None and decrypt_optional(blob) == "0901234567"


def test_encrypt_decimal_preserves_precision() -> None:
    value = Decimal("12345678.99")
    blob = encrypt_decimal(value)
    assert blob is not None
    assert decrypt_decimal(blob) == value
    assert encrypt_decimal(None) is None
    assert decrypt_decimal(None) is None


# --------------------------------------------------------------------------- #
# JSONB encrypted-field helpers                                               #
# --------------------------------------------------------------------------- #
def test_encrypt_for_json_roundtrip_and_marker() -> None:
    enc = encrypt_for_json("secret-note")
    assert enc.startswith("enc:")
    assert is_encrypted_json(enc) is True
    assert is_encrypted_json("plain") is False
    assert decrypt_from_json(enc) == "secret-note"


def test_decrypt_from_json_rejects_unmarked() -> None:
    with pytest.raises(ValueError, match="not an encrypted"):
        decrypt_from_json("plain-value")


# --------------------------------------------------------------------------- #
# Blind index                                                                 #
# --------------------------------------------------------------------------- #
def test_blind_index_is_deterministic_and_normalized() -> None:
    assert blind_index("012345678901") == blind_index("  012345678901  ")
    assert blind_index("ABC123") == blind_index("abc123")
    assert blind_index("a") != blind_index("b")
    assert len(blind_index("a")) == 64  # sha256 hexdigest


# --------------------------------------------------------------------------- #
# Password hashing (Argon2id)                                                 #
# --------------------------------------------------------------------------- #
def test_password_hash_and_verify() -> None:
    hashed = hash_password("S3cret!pass")
    assert hashed != "S3cret!pass"
    assert hashed.startswith("$argon2")
    assert verify_password("S3cret!pass", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_verify_password_never_raises_on_garbage() -> None:
    assert verify_password("x", "not-a-valid-hash") is False


# --------------------------------------------------------------------------- #
# JWT access tokens                                                           #
# --------------------------------------------------------------------------- #
def test_create_and_decode_access_token() -> None:
    token = create_access_token(
        subject=42, roles=["ADMIN"], permissions=["user:manage", "payroll:run"]
    )
    claims = decode_access_token(token)
    assert claims["sub"] == "42"
    assert claims["typ"] == "access"
    assert set(claims["perms"]) == {"user:manage", "payroll:run"}
    assert "jti" in claims


def test_decode_rejects_tampered_token() -> None:
    token = create_access_token(subject=1, roles=[], permissions=[])
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token + "tamper")


def test_decode_rejects_non_access_token() -> None:
    # A token signed with the right key but wrong typ must be rejected.
    from app.core.config import settings

    bad = jwt.encode(
        {"sub": "1", "typ": "refresh", "exp": 9999999999},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(bad)


# --------------------------------------------------------------------------- #
# Opaque refresh tokens                                                       #
# --------------------------------------------------------------------------- #
def test_refresh_token_generation_and_hashing() -> None:
    raw = generate_refresh_token()
    assert len(raw) >= 40
    assert generate_refresh_token() != raw  # unique
    digest = hash_token(raw)
    assert len(digest) == 64  # sha256 hex
    assert hash_token(raw) == digest  # deterministic
