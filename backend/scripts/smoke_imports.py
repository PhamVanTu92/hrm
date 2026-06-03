"""Import-level smoke test (no DB/Redis required).

Imports every module, builds the FastAPI app, and loads the Celery app so that
syntax errors, bad imports, circular imports and broken config validation are
caught fast — before any container or database is involved.

Run:
    python -m scripts.smoke_imports
Requires the crypto/JWT/DB env vars to be set (config validation). The DB is
never contacted; only the connection string is parsed.
"""

from __future__ import annotations

import importlib

MODULES = [
    "app.core.config",
    "app.core.security",
    "app.core.encryption",
    "app.core.rbac",
    "app.core.exceptions",
    "app.core.logging",
    "app.core.redis",
    "app.core.events",
    "app.core.pagination",
    "app.db.base",
    "app.db.session",
    "app.db.repository",
    "app.db.registry",
    "app.modules.auth.models",
    "app.modules.auth.schemas",
    "app.modules.auth.repository",
    "app.modules.auth.service",
    "app.modules.auth.routes",
    "app.modules.employee.models",
    "app.modules.employee.schemas",
    "app.modules.employee.repository",
    "app.modules.employee.service",
    "app.modules.employee.routes",
    "app.audit.models",
    "app.audit.masking",
    "app.audit.recorder",
    "app.middleware.rate_limit",
    "app.middleware.request_context",
    "app.middleware.secure_headers",
    "app.api.router",
    "app.core.celery_app",
    "app.workers.attendance_tasks",
    "app.workers.payroll_tasks",
    "app.workers.pdf_tasks",
    "app.workers.email_tasks",
    "app.workers.maintenance_tasks",
    "app.main",
]


def main() -> int:
    for name in MODULES:
        importlib.import_module(name)
        print("OK", name)

    from app.core.celery_app import celery_app
    from app.main import app

    app_tasks = sorted(t for t in celery_app.tasks if t.startswith("app."))
    print("ROUTES", len(app.routes))
    print("CELERY_TASKS", len(app_tasks))
    for t in app_tasks:
        print("  task", t)
    print("ALL IMPORTS OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
