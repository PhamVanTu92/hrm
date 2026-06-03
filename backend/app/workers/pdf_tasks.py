"""Payslip PDF generation + encryption tasks.

Renders the payslip HTML to a PDF, password-protects it with the employee's
CCCD, uploads it to object storage (MinIO/S3) and hands off to the email queue.
The heavy lifting lives in ``PayslipService.generate_and_store``; this wrapper
provides the Celery entry point, retry policy and queue routing.
"""

from __future__ import annotations

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.workers._util import run_async

logger = get_logger("worker.pdf")


@celery_app.task(
    bind=True,
    name="app.workers.pdf_tasks.gen_payslip_pdf",
    max_retries=3,
    default_retry_delay=60,
    queue="pdf",
)
def gen_payslip_pdf(self, run_item_id: int) -> None:  # type: ignore[no-untyped-def]
    """Render payslip PDF -> encrypt (CCCD) -> upload, then queue the email."""

    async def _generate() -> int:
        async with SessionLocal() as session:
            from app.modules.payslip.service import PayslipService

            payslip = await PayslipService(session).generate_and_store(run_item_id)
            await session.commit()
            return payslip.id

    try:
        logger.info("payslip_pdf_generate", run_item_id=run_item_id)
        payslip_id = run_async(_generate())
        from app.workers.email_tasks import send_payslip_email

        send_payslip_email.delay(payslip_id=payslip_id)
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc) from exc
