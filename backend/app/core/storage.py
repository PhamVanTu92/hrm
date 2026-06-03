"""Object storage (S3 / MinIO) abstraction.

A thin wrapper over an S3-compatible client (works against AWS S3 or a local
MinIO via ``S3_ENDPOINT``). Used for payslip PDFs and document attachments.

``boto3`` is imported lazily so importing this module never requires the SDK
(keeps unit tests and tooling light); the client is created on first use and
cached. In tests, monkeypatch :meth:`ObjectStorage.put_object` /
:meth:`get_object` to avoid any network.
"""

from __future__ import annotations

from functools import cached_property
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("storage")


class StorageError(RuntimeError):
    """Raised when an object-storage operation fails."""


class ObjectStorage:
    """S3-compatible object storage client."""

    def __init__(self, bucket: str | None = None) -> None:
        self.bucket = bucket or settings.S3_BUCKET

    @cached_property
    def _client(self) -> Any:
        """Lazily build and cache a boto3 S3 client."""
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise StorageError("boto3 chưa được cài đặt") from exc

        return boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )

    def ensure_bucket(self) -> None:
        """Create the bucket if it does not exist (idempotent, for MinIO setup)."""
        client = self._client
        try:
            client.head_bucket(Bucket=self.bucket)
        except Exception:  # noqa: BLE001 - any miss => try to create
            client.create_bucket(Bucket=self.bucket)
            logger.info("storage_bucket_created", bucket=self.bucket)

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        """Upload bytes under ``key``; returns the key."""
        try:
            self._client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Tải lên thất bại: {key}") from exc
        logger.info("storage_put", key=key, size=len(data))
        return key

    def get_object(self, key: str) -> bytes:
        """Download and return the bytes stored under ``key``."""
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Tải xuống thất bại: {key}") from exc

    def delete_object(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Xóa thất bại: {key}") from exc


# Module-level singleton used across the app.
storage = ObjectStorage()
