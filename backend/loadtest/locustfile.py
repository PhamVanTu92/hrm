"""Locust load profile for the HRM API.

Run (after seeding data + creating the LOADTEST_USER):

    pip install ".[loadtest]"
    LOADTEST_USER=admin LOADTEST_PASS='...' \
        locust -f loadtest/locustfile.py --host http://localhost:8000

Then open http://localhost:8089 to drive the swarm. Each simulated user logs
in once, then exercises read-heavy endpoints (the realistic dashboard load).
Payroll calculation is intentionally NOT hammered here — it is a batch job run
via Celery, not an interactive endpoint.
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task

_USER = os.environ.get("LOADTEST_USER", "admin")
_PASS = os.environ.get("LOADTEST_PASS", "ChangeMe!123")
_API = "/api/v1"


class HrmUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        resp = self.client.post(
            f"{_API}/auth/login",
            json={"username": _USER, "password": _PASS},
            name="POST /auth/login",
        )
        token = resp.json().get("access_token") if resp.status_code == 200 else None
        self.client.headers.update({"Authorization": f"Bearer {token}"} if token else {})

    @task(5)
    def list_employees(self) -> None:
        self.client.get(f"{_API}/employees?page=1&size=20", name="GET /employees")

    @task(2)
    def my_pending(self) -> None:
        self.client.get(f"{_API}/approvals/my-pending", name="GET /approvals/my-pending")

    @task(2)
    def list_components(self) -> None:
        self.client.get(f"{_API}/payroll/components", name="GET /payroll/components")

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="GET /health")
