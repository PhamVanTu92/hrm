"""Attendance batch tasks.

Pipeline: pull raw punches from time-clock devices -> upsert raw logs
(idempotent) -> normalize into daily records -> aggregate monthly.

The device adapters live in ``app.modules.attendance.adapters`` and the
business logic in ``AttendanceService``; these task wrappers provide the Celery
entry points, retry policy and queue routing, bridging sync Celery to the async
service via :func:`run_async`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.core.celery_app import celery_app
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.modules.attendance.adapters import build_adapter
from app.modules.attendance.repository import DeviceRepository
from app.modules.attendance.service import AttendanceService
from app.workers._util import run_async

logger = get_logger("worker.attendance")


@celery_app.task(name="app.workers.attendance_tasks.pull_all_devices")
def pull_all_devices() -> None:
    """Beat entry point (23:00). Fan out one task per active device."""

    async def _active_ids() -> list[int]:
        async with SessionLocal() as session:
            return [d.id for d in await DeviceRepository(session).active_devices()]

    ids = run_async(_active_ids())
    logger.info("attendance_pull_started", devices=len(ids))
    for device_id in ids:
        pull_device.delay(device_id)


@celery_app.task(
    bind=True,
    name="app.workers.attendance_tasks.pull_device",
    max_retries=3,
    default_retry_delay=300,
    queue="attendance",
)
def pull_device(self, device_id: int) -> None:  # type: ignore[no-untyped-def]
    """Pull + upsert raw logs for one device, then trigger normalization."""

    async def _pull() -> str | None:
        async with SessionLocal() as session:
            service = AttendanceService(session)
            device = await service.devices.get(device_id)
            if device is None or not device.is_active:
                return None
            adapter = build_adapter(device)
            punches = adapter.fetch_logs(device.last_ingest_at)
            await service.ingest_punches(device_id, punches)
            device.last_ingest_at = datetime.now(UTC)
            await session.commit()
            return datetime.now(UTC).date().isoformat()

    try:
        work_date = run_async(_pull())
        if work_date is not None:
            normalize_daily.delay(device_id, work_date)
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc) from exc


@celery_app.task(
    bind=True,
    name="app.workers.attendance_tasks.normalize_daily",
    max_retries=3,
    queue="attendance",
)
def normalize_daily(self, device_id: int, work_date: str) -> int:  # type: ignore[no-untyped-def]
    """Normalize raw punches into ``attendance_daily`` for a given date."""

    async def _normalize() -> int:
        async with SessionLocal() as session:
            count = await AttendanceService(session).normalize_device_day(
                device_id, date.fromisoformat(work_date)
            )
            await session.commit()
            return count

    try:
        count = run_async(_normalize())
        logger.info("attendance_normalize", device_id=device_id, work_date=work_date, count=count)
        return count
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc) from exc


@celery_app.task(name="app.workers.attendance_tasks.aggregate_monthly", queue="attendance")
def aggregate_monthly(period: str) -> int:
    """Aggregate daily records into ``attendance_monthly`` for a period."""

    async def _aggregate() -> int:
        async with SessionLocal() as session:
            affected = await AttendanceService(session).aggregate_monthly(period)
            await session.commit()
            return affected

    affected = run_async(_aggregate())
    logger.info("attendance_aggregate_monthly", period=period, employees=affected)
    return affected
