"""Tests for the /metrics endpoint and request metrics middleware."""

from __future__ import annotations

from httpx import AsyncClient


async def test_metrics_endpoint_exposes_prometheus(client: AsyncClient) -> None:
    # Generate at least one tracked request first.
    await client.get("/health")
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body


async def test_metrics_uses_route_template_label(client: AsyncClient) -> None:
    # Hit a parameterised route; the metric label must be the template, not the
    # concrete id, to avoid unbounded cardinality.
    await client.get("/api/v1/employees/999", headers={})
    resp = await client.get("/metrics")
    assert "/api/v1/employees/{employee_id}" in resp.text
