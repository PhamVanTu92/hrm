"""Tests for the payslip module.

The render -> encrypt -> upload pipeline is tested with the heavy native libs
(WeasyPrint/pikepdf) and object storage monkeypatched, so the test suite stays
lightweight; the real libs run in the Docker image.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_decimal
from app.core.exceptions import ConflictError, PermissionDenied
from app.core.rbac import CurrentUser
from app.core.storage import storage
from app.modules.employee.models import Employee
from app.modules.payroll.repository import RunItemRepository
from app.modules.payroll.service import PayrollService
from app.modules.payslip.models import FileAttachment, PayslipStatus
from app.modules.payslip.repository import PayslipRepository
from app.modules.payslip.service import PayslipService, render_payslip_html
from tests.conftest import API

HeaderFactory = Callable[..., dict[str, str]]
PERIOD = "2026-05"


def _payroll_actor() -> CurrentUser:
    return CurrentUser(id=1, perms={"payroll:run", "payroll:lock"})


async def _calculated_run(session: AsyncSession, *, user_id: int | None = None):  # noqa: ANN202
    """Build a 1-employee run with a computed item; return (run, employee)."""
    svc = PayrollService(session)
    await svc.create_component(
        code="NET", name="Net", value_type="FORMULA", var_code="TONG_LUONG", expression="luong_cung"
    )
    emp = Employee(
        employee_code="E1",
        full_name="Nguyễn Văn A",
        user_id=user_id,
        enc_base_salary=encrypt_decimal(Decimal("10000000")),
    )
    session.add(emp)
    await session.flush()
    run = await svc.create_run(PERIOD, _payroll_actor())
    await svc.calculate_run(run.id)
    return run, emp


# --------------------------------------------------------------------------- #
# Prepare                                                                     #
# --------------------------------------------------------------------------- #
async def test_prepare_creates_pending_payslips(db_session: AsyncSession) -> None:
    run, emp = await _calculated_run(db_session)
    svc = PayslipService(db_session)
    assert await svc.prepare_for_run(run.id) == 1
    # Idempotent: a second prepare creates nothing.
    assert await svc.prepare_for_run(run.id) == 0

    payslips = await PayslipRepository(db_session).list_for_employee(emp.id)
    assert len(payslips) == 1
    assert payslips[0].status == PayslipStatus.PENDING
    assert payslips[0].period == PERIOD


# --------------------------------------------------------------------------- #
# Confirm / reject + ownership                                                #
# --------------------------------------------------------------------------- #
async def test_confirm_then_cannot_reconfirm(db_session: AsyncSession) -> None:
    run, emp = await _calculated_run(db_session)
    svc = PayslipService(db_session)
    await svc.prepare_for_run(run.id)
    payslip = (await PayslipRepository(db_session).list_for_employee(emp.id))[0]

    actor = CurrentUser(id=99, employee_id=emp.id)
    confirmed = await svc.confirm(payslip.id, actor)
    assert confirmed.status == PayslipStatus.CONFIRMED
    assert confirmed.confirmed_at is not None

    with pytest.raises(ConflictError):
        await svc.confirm(payslip.id, actor)


async def test_reject_records_feedback(db_session: AsyncSession) -> None:
    run, emp = await _calculated_run(db_session)
    svc = PayslipService(db_session)
    await svc.prepare_for_run(run.id)
    payslip = (await PayslipRepository(db_session).list_for_employee(emp.id))[0]

    rejected = await svc.reject(
        payslip.id, "Sai số liệu thưởng", CurrentUser(id=99, employee_id=emp.id)
    )
    assert rejected.status == PayslipStatus.REJECTED
    assert rejected.feedback == "Sai số liệu thưởng"


async def test_cannot_view_others_payslip(db_session: AsyncSession) -> None:
    run, emp = await _calculated_run(db_session)
    svc = PayslipService(db_session)
    await svc.prepare_for_run(run.id)
    payslip = (await PayslipRepository(db_session).list_for_employee(emp.id))[0]

    # A different employee, no payroll:read -> denied.
    with pytest.raises(PermissionDenied):
        await svc.get_for_view(payslip.id, CurrentUser(id=99, employee_id=emp.id + 999))
    # payroll:read can view any.
    seen = await svc.get_for_view(payslip.id, CurrentUser(id=1, perms={"payroll:read"}))
    assert seen.id == payslip.id


# --------------------------------------------------------------------------- #
# HTML render (pure)                                                          #
# --------------------------------------------------------------------------- #
def test_render_payslip_html() -> None:
    html = render_payslip_html(
        employee_code="E1",
        full_name="Nguyễn Văn A",
        period=PERIOD,
        result={"luong_thang": 10000000.0, "TONG_LUONG": 11000000.0},
    )
    assert "PHIẾU LƯƠNG" in html
    assert "E1" in html
    assert "11,000,000.00" in html  # net, formatted
    assert "luong_thang" in html


# --------------------------------------------------------------------------- #
# Generate + store (heavy libs + storage monkeypatched)                       #
# --------------------------------------------------------------------------- #
async def test_generate_and_store_uploads_and_links(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, emp = await _calculated_run(db_session)
    svc = PayslipService(db_session)
    await svc.prepare_for_run(run.id)
    item = await RunItemRepository(db_session).get_for(run.id, emp.id)

    monkeypatch.setattr("app.modules.payslip.service._render_pdf", lambda html: b"%PDF-1.4 fake")
    monkeypatch.setattr(
        "app.modules.payslip.service._encrypt_pdf", lambda pdf, password: b"ENC:" + pdf
    )
    uploaded: dict[str, object] = {}

    def _fake_put(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        uploaded["key"] = key
        uploaded["data"] = data
        return key

    monkeypatch.setattr(storage, "put_object", _fake_put)

    payslip = await svc.generate_and_store(item.id)

    assert uploaded["key"] == f"payslips/{PERIOD}/E1.pdf"
    assert uploaded["data"] == b"ENC:%PDF-1.4 fake"
    assert payslip.file_id is not None
    attachment = await db_session.get(FileAttachment, payslip.file_id)
    assert attachment is not None and attachment.encrypted is True
    assert attachment.object_key == f"payslips/{PERIOD}/E1.pdf"


# --------------------------------------------------------------------------- #
# API                                                                         #
# --------------------------------------------------------------------------- #
async def test_prepare_and_me_via_api(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    run, emp = await _calculated_run(db_session, user_id=7777)

    prepared = await client.post(
        f"{API}/payslips/runs/{run.id}/prepare", headers=auth_header(perms=["payroll:lock"])
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["data"]["created"] == 1

    # The employee (user 7777) sees their own payslip.
    mine = await client.get(f"{API}/payslips/me", headers=auth_header(sub=7777, perms=[]))
    assert mine.status_code == 200
    assert len(mine.json()["data"]) == 1


async def test_prepare_requires_lock_perm(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    run, _emp = await _calculated_run(db_session)
    resp = await client.post(
        f"{API}/payslips/runs/{run.id}/prepare", headers=auth_header(perms=["payroll:run"])
    )
    assert resp.status_code == 403


async def test_download_streams_pdf(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_header: HeaderFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, emp = await _calculated_run(db_session, user_id=8888)
    svc = PayslipService(db_session)
    await svc.prepare_for_run(run.id)
    item = await RunItemRepository(db_session).get_for(run.id, emp.id)
    monkeypatch.setattr("app.modules.payslip.service._render_pdf", lambda html: b"PDF")
    monkeypatch.setattr("app.modules.payslip.service._encrypt_pdf", lambda pdf, pw: b"ENC")
    monkeypatch.setattr(storage, "put_object", lambda key, data, content_type="x": key)
    await svc.generate_and_store(item.id)
    payslip = (await PayslipRepository(db_session).list_for_employee(emp.id))[0]

    monkeypatch.setattr(storage, "get_object", lambda key: b"ENC")
    resp = await client.get(
        f"{API}/payslips/{payslip.id}/download", headers=auth_header(sub=8888, perms=[])
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"ENC"
