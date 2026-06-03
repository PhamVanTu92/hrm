"""Outbound email tasks.

All transactional mail (payslips, account notices, approval reminders) is sent
from here so the HTTP request path never blocks on SMTP. Sends are:
- retried with exponential backoff on transient SMTP failures,
- idempotent: a Redis marker keyed by the logical message id prevents a
  re-delivered task (``task_acks_late``) from mailing the same recipient twice.

The actual SMTP transport is intentionally thin; swap ``_send_smtp`` for a
provider SDK (SES, SendGrid) without touching the task contract.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.db.session import SessionLocal
from app.workers._util import run_async

logger = get_logger("worker.email")

# How long the "already sent" marker lives. Long enough to cover any retry
# storm / redelivery window, short enough not to leak keys forever.
_DEDUP_TTL_SECONDS = 7 * 24 * 3600


def _already_sent(dedup_key: str) -> bool:
    """Return True if a message with this key was already delivered.

    Uses ``SET key value NX`` semantics: the first caller claims the key and
    proceeds; any redelivery finds the key present and short-circuits.
    """

    async def _claim() -> bool:
        redis = get_redis()
        # NX => only set if absent; returns None when the key already exists.
        claimed = await redis.set(dedup_key, "1", ex=_DEDUP_TTL_SECONDS, nx=True)
        return claimed is None

    return run_async(_claim())


def _release_marker(dedup_key: str) -> None:
    """Drop the dedup marker so a later retry is allowed to send again."""

    async def _drop() -> None:
        redis = get_redis()
        await redis.delete(dedup_key)

    run_async(_drop())


def _send_smtp(message: EmailMessage) -> None:
    """Deliver one message over SMTP.

    Kept synchronous and isolated so it can be swapped for a provider SDK.
    Raises on any transport error; the caller's retry policy handles it.
    """
    host = settings.SMTP_HOST
    if not host:
        raise RuntimeError("SMTP_HOST is not configured")
    port = settings.SMTP_PORT
    if settings.SMTP_USE_SSL:
        client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=settings.SMTP_TIMEOUT)
    else:
        client = smtplib.SMTP(host, port, timeout=settings.SMTP_TIMEOUT)
    try:
        if settings.SMTP_USE_TLS:
            client.starttls()
        if settings.SMTP_USER:
            client.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
        client.send_message(message)
    finally:
        client.quit()


def _build_message(
    *,
    to: str,
    subject: str,
    body: str,
    attachment: bytes | None = None,
    attachment_name: str | None = None,
) -> EmailMessage:
    """Assemble a (optionally) one-attachment email message."""
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if attachment is not None and attachment_name is not None:
        message.add_attachment(
            attachment,
            maintype="application",
            subtype="pdf",
            filename=attachment_name,
        )
    return message


def _load_payslip_context(payslip_id: int) -> dict | None:
    """Resolve recipient email, period and object key for a payslip."""

    async def _load() -> dict | None:
        from app.modules.auth.models import User
        from app.modules.employee.models import Employee
        from app.modules.payslip.repository import FileAttachmentRepository, PayslipRepository

        async with SessionLocal() as session:
            payslip = await PayslipRepository(session).get(payslip_id)
            if payslip is None:
                return None
            to: str | None = None
            employee = await session.get(Employee, payslip.employee_id)
            if employee is not None and employee.user_id is not None:
                user = await session.get(User, employee.user_id)
                to = user.email if user else None
            key: str | None = None
            if payslip.file_id is not None:
                attachment = await FileAttachmentRepository(session).get(payslip.file_id)
                key = attachment.object_key if attachment else None
            return {"to": to, "period": payslip.period, "key": key}

    return run_async(_load())


def _mark_payslip_sent(payslip_id: int) -> None:
    async def _mark() -> None:
        from app.modules.payslip.service import PayslipService

        async with SessionLocal() as session:
            await PayslipService(session).mark_email_sent(payslip_id)
            await session.commit()

    run_async(_mark())


def _mark_payslip_failed(payslip_id: int) -> None:
    async def _mark() -> None:
        from app.modules.payslip.service import PayslipService

        async with SessionLocal() as session:
            await PayslipService(session).mark_email_failed(payslip_id)
            await session.commit()

    run_async(_mark())


@celery_app.task(
    bind=True,
    name="app.workers.email_tasks.send_payslip_email",
    queue="email",
    max_retries=5,
    retry_backoff=True,  # 1s, 2s, 4s, 8s, ... between retries
    retry_backoff_max=600,
    retry_jitter=True,
    acks_late=True,
)
def send_payslip_email(self, *, payslip_id: int) -> None:  # type: ignore[no-untyped-def]
    """Email a generated payslip PDF to one employee.

    The PDF was rendered + password-protected + uploaded by
    :mod:`app.workers.pdf_tasks`; here we load the payslip, fetch the encrypted
    PDF from object storage and deliver it. Idempotent on ``payslip_id`` so a
    redelivered task does not re-send; updates the payslip's email status.
    """
    dedup_key = f"email:payslip:sent:{payslip_id}"
    if _already_sent(dedup_key):
        logger.info("payslip_email_skipped_duplicate", payslip_id=payslip_id)
        return

    ctx = _load_payslip_context(payslip_id)
    if ctx is None or not ctx["to"]:
        logger.warning("payslip_email_no_recipient", payslip_id=payslip_id)
        _release_marker(dedup_key)
        return

    try:
        from app.core.storage import storage

        logger.info("payslip_email_send", payslip_id=payslip_id, period=ctx["period"])
        pdf_bytes = storage.get_object(ctx["key"]) if ctx["key"] else b""
        message = _build_message(
            to=ctx["to"],
            subject=f"[HRM] Phiếu lương kỳ {ctx['period']}",
            body=(
                "Kính gửi Anh/Chị,\n\n"
                f"Phiếu lương kỳ {ctx['period']} được đính kèm (định dạng PDF, "
                "mở bằng 6 số cuối CCCD của bạn).\n\n"
                "Trân trọng,\nPhòng Nhân sự"
            ),
            attachment=pdf_bytes or None,
            attachment_name=f"payslip_{ctx['period']}.pdf",
        )
        _send_smtp(message)
        _mark_payslip_sent(payslip_id)
        logger.info("payslip_email_sent", payslip_id=payslip_id)
    except Exception as exc:  # noqa: BLE001
        _release_marker(dedup_key)
        _mark_payslip_failed(payslip_id)
        logger.warning(
            "payslip_email_failed",
            payslip_id=payslip_id,
            attempt=self.request.retries + 1,
            error=str(exc),
        )
        raise self.retry(exc=exc) from exc


@celery_app.task(
    bind=True,
    name="app.workers.email_tasks.send_notification_email",
    queue="email",
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    acks_late=True,
)
def send_notification_email(  # type: ignore[no-untyped-def]
    self,
    *,
    to: str,
    subject: str,
    body: str,
    dedup_id: str | None = None,
) -> None:
    """Generic transactional notification (approvals, account events).

    Pass a stable ``dedup_id`` for at-most-once semantics; omit it for mail
    where an occasional duplicate is acceptable.
    """
    dedup_key = f"email:notify:sent:{dedup_id}" if dedup_id else None
    if dedup_key and _already_sent(dedup_key):
        logger.info("notification_email_skipped_duplicate", dedup_id=dedup_id)
        return

    try:
        logger.info("notification_email_send", to=to, subject=subject)
        _send_smtp(_build_message(to=to, subject=subject, body=body))
        logger.info("notification_email_sent", to=to)
    except Exception as exc:  # noqa: BLE001
        if dedup_key:
            _release_marker(dedup_key)
        logger.warning(
            "notification_email_failed",
            to=to,
            attempt=self.request.retries + 1,
            error=str(exc),
        )
        raise self.retry(exc=exc) from exc
