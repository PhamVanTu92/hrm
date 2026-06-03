"""Payroll calculation tasks.

A payroll run for N employees is split into chunks and executed in parallel via
a Celery ``chord``; the callback finalizes the run. This scales to 10k+
employees by adding workers on the ``payroll`` queue. Each chunk calls the same
``PayrollService.calculate_run`` used by the synchronous API, restricted to its
slice of employee ids.
"""

from __future__ import annotations

from celery import chord, group

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.workers._util import run_async

logger = get_logger("worker.payroll")

CHUNK_SIZE = 500


@celery_app.task(name="app.workers.payroll_tasks.run_payroll", queue="payroll")
def run_payroll(run_id: int, employee_ids: list[int]) -> None:
    """Split a payroll run into parallel chunks + a finalize callback."""
    logger.info("payroll_run_started", run_id=run_id, employees=len(employee_ids))
    chunks = [employee_ids[i : i + CHUNK_SIZE] for i in range(0, len(employee_ids), CHUNK_SIZE)]
    header = group(calc_chunk.s(run_id, chunk) for chunk in chunks)
    chord(header)(finalize_run.s(run_id))


@celery_app.task(
    bind=True,
    name="app.workers.payroll_tasks.calc_chunk",
    max_retries=2,
    queue="payroll",
)
def calc_chunk(self, run_id: int, employee_ids: list[int]) -> int:  # type: ignore[no-untyped-def]
    """Calculate payroll for a chunk of employees using the formula engine."""

    async def _calc() -> int:
        async with SessionLocal() as session:
            from app.modules.payroll.service import PayrollService

            count = await PayrollService(session).calculate_run(run_id, employee_ids=employee_ids)
            await session.commit()
            return count

    try:
        count = run_async(_calc())
        logger.info("payroll_calc_chunk", run_id=run_id, size=count)
        return count
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc) from exc


@celery_app.task(name="app.workers.payroll_tasks.finalize_run", queue="payroll")
def finalize_run(chunk_results: list[int], run_id: int) -> None:
    """Chord callback: mark the run as calculated once all chunks finish."""
    total = sum(chunk_results)
    logger.info("payroll_run_finalized", run_id=run_id, total_items=total)
