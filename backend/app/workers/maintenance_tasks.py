"""Periodic maintenance tasks (beat-driven).

These keep the system healthy without operator intervention:
- :func:`check_escalations` nudges approval requests that have sat too long.
- :func:`ensure_next_partitions` pre-creates next month's ``audit_logs``
  partition so inserts never hit the catch-all DEFAULT partition.

Both run on the ``default`` queue and are safe to re-run (idempotent).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.workers._util import run_async

logger = get_logger("worker.maintenance")


def _next_month(today: date) -> tuple[int, int]:
    """Return (year, month) for the month following ``today``."""
    if today.month == 12:
        return today.year + 1, 1
    return today.year, today.month + 1


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    """Return [start, end) covering the whole of the given month."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


@celery_app.task(name="app.workers.maintenance_tasks.ensure_next_partitions")
def ensure_next_partitions() -> str:
    """Create next month's range partition for ``audit_logs`` if absent.

    audit_logs is range-partitioned by ``created_at`` (see migration 0001).
    Beat runs this on the 25th so the partition exists before the month rolls
    over; ``CREATE TABLE IF NOT EXISTS`` makes it idempotent.
    """
    year, month = _next_month(date.today())
    start, end = _month_bounds(year, month)
    partition = f"audit_logs_{year:04d}_{month:02d}"
    ddl = (
        f'CREATE TABLE IF NOT EXISTS "{partition}" '
        "PARTITION OF audit_logs "
        f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
    )

    async def _run() -> None:
        async with SessionLocal() as session:
            await session.execute(text(ddl))
            await session.commit()

    run_async(_run())
    logger.info("audit_partition_ensured", partition=partition)
    return partition


@celery_app.task(name="app.workers.maintenance_tasks.check_escalations")
def check_escalations() -> int:
    """Find approval requests past their SLA and escalate them.

    Runs every 30 minutes. The approval module owns the escalation rules;
    this task is the scheduler hook that drives them. Returns the number of
    requests escalated (0 until the approval module lands).
    """

    async def _run() -> int:
        from app.modules.approval.service import ApprovalService

        async with SessionLocal() as session:
            escalated = await ApprovalService(session).escalate_overdue()
            await session.commit()
            return escalated

    escalated = run_async(_run())
    logger.info("approval_escalations_checked", escalated=escalated)
    return escalated
