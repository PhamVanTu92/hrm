"""AES-256-GCM field-level encryption + searchable blind index.

Sensitive HR data (salary, national id, bank account, phone) is encrypted at
the application layer before being written to the database as ``BYTEA``. Even a
``SELECT *`` by a DBA or a leaked backup only exposes ciphertext.

Ciphertext layout (bytes)::

    [ version:1 ][ nonce:12 ][ ciphertext+tag:variable ]

The 1-byte version prefix enables key rotation: decryption picks the key for
the embedded version; new writes use the current key version.
"""

from __future__ import annotations

import base64
import hmac
import os
from decimal import Decimal
from hashlib import sha256

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_CURRENT_KEY_VERSION = 1
_NONCE_SIZE = 12

# Registry of key versions -> raw key bytes. To rotate, add a new version with a
# new key and bump _CURRENT_KEY_VERSION; old ciphertext stays decryptable.
_KEYS: dict[int, bytes] = {
    1: settings.aes_key,
}

# Prefix used to mark encrypted values stored inside JSONB (dynamic profiles).
ENC_PREFIX = "enc:"


def encrypt(plaintext: str) -> bytes:
    """Encrypt a string, returning versioned binary ciphertext for ``BYTEA``."""
    key = _KEYS[_CURRENT_KEY_VERSION]
    nonce = os.urandom(_NONCE_SIZE)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return bytes([_CURRENT_KEY_VERSION]) + nonce + ct


def decrypt(blob: bytes) -> str:
    """Decrypt versioned binary ciphertext produced by :func:`encrypt`."""
    version = blob[0]
    key = _KEYS.get(version)
    if key is None:
        raise ValueError(f"Unknown AES key version: {version}")
    nonce = blob[1 : 1 + _NONCE_SIZE]
    ct = blob[1 + _NONCE_SIZE :]
    return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")


def encrypt_optional(plaintext: str | None) -> bytes | None:
    """Encrypt only when value is present."""
    return None if plaintext is None or plaintext == "" else encrypt(plaintext)


def decrypt_optional(blob: bytes | None) -> str | None:
    """Decrypt only when ciphertext is present."""
    return None if blob is None else decrypt(blob)


def encrypt_decimal(value: Decimal | float | int | None) -> bytes | None:
    """Encrypt a monetary value. Stored as plain decimal string for precision."""
    if value is None:
        return None
    return encrypt(str(Decimal(str(value))))


def decrypt_decimal(blob: bytes | None) -> Decimal | None:
    """Decrypt a monetary value back into ``Decimal``."""
    if blob is None:
        return None
    return Decimal(decrypt(blob))


# ---- JSONB helpers (dynamic profile encrypted fields) ----


def encrypt_for_json(plaintext: str) -> str:
    """Encrypt and base64-encode with the ``enc:`` prefix for JSONB storage."""
    return ENC_PREFIX + base64.b64encode(encrypt(plaintext)).decode("ascii")


def decrypt_from_json(value: str) -> str:
    """Reverse :func:`encrypt_for_json`."""
    if not value.startswith(ENC_PREFIX):
        raise ValueError("Value is not an encrypted JSON field")
    return decrypt(base64.b64decode(value[len(ENC_PREFIX) :]))


def is_encrypted_json(value: object) -> bool:
    """Return ``True`` if a JSON value is an encrypted field marker."""
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


# ---- Blind index (deterministic, for equality search on encrypted data) ----


def blind_index(plaintext: str) -> str:
    """Compute a deterministic HMAC-SHA256 index for exact-match search.

    Allows querying an encrypted column by exact value (e.g. find by national
    id) without ever storing or revealing the plaintext. Normalised to lower
    case + stripped so equality is stable.
    """
    normalized = plaintext.strip().lower().encode("utf-8")
    return hmac.new(settings.blind_index_key, normalized, sha256).hexdigest()
