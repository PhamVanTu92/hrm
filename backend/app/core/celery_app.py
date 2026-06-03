"""Celery application + queue routing + beat schedule.

Heavy / batch work runs here, never inside an HTTP request:
- attendance: nightly pull from time clocks, normalization
- payroll: chunked salary calculation
- pdf: payslip generation + encryption
- email: outbound mail with retry
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "hrm",
    broker=str(settings.CELERY_BROKER_URL),
    backend=str(settings.CELERY_RESULT_BACKEND),
    include=[
        "app.workers.attendance_tasks",
        "app.workers.payroll_tasks",
        "app.workers.pdf_tasks",
        "app.workers.email_tasks",
        "app.workers.maintenance_tasks",
    ],
)

celery_app.conf.update(
    task_acks_late=True,  # re-deliver if a worker dies mid-task
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # fair dispatch for long tasks
    task_track_started=True,
    task_default_queue="default",
    timezone=settings.TIMEZONE,
    enable_utc=True,
    result_expires=3600,
    task_routes={
        "app.workers.attendance_tasks.*": {"queue": "attendance"},
        "app.workers.payroll_tasks.*": {"queue": "payroll"},
        "app.workers.pdf_tasks.*": {"queue": "pdf"},
        "app.workers.email_tasks.*": {"queue": "email"},
    },
)

# ---- Beat schedule (use RedBeat in prod: -S redbeat.RedBeatScheduler) ----
celery_app.conf.beat_schedule = {
    "pull-attendance-nightly": {
        "task": "app.workers.attendance_tasks.pull_all_devices",
        "schedule": crontab(hour=23, minute=0),
    },
    "check-approval-escalations": {
        "task": "app.workers.maintenance_tasks.check_escalations",
        "schedule": crontab(minute="*/30"),
    },
    "ensure-next-partitions": {
        "task": "app.workers.maintenance_tasks.ensure_next_partitions",
        "schedule": crontab(day_of_month=25, hour=1, minute=0),
    },
}
