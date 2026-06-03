"""Integration tests for the employee module.

Covers CRUD, at-rest encryption, blind-index search, RBAC enforcement,
pagination/filtering and dynamic-profile validation + masking.
"""

from __future__ import annotations

from collections.abc import Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import blind_index, decrypt_optional
from app.core.rbac import CurrentUser
from app.modules.employee.models import Employee, ProfileCategory, ProfileField
from app.modules.employee.repository import EmployeeRepository
from app.modules.employee.schemas import EmployeeCreate
from app.modules.employee.service import EmployeeService
from tests.conftest import API

HeaderFactory = Callable[..., dict[str, str]]


def _emp_payload(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "employee_code": "E001",
        "full_name": "Nguyen Van A",
        "national_id": "012345678901",
        "phone": "0901234567",
        "bank_account": "1234567890",
        "base_salary": "25000000.00",
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# Create / read + encryption                                                  #
# --------------------------------------------------------------------------- #
async def test_create_employee_then_read_non_sensitive(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    writer = auth_header(perms=["employee:write"])
    created = await client.post(f"{API}/employees", json=_emp_payload(), headers=writer)
    assert created.status_code == 201, created.text
    emp = created.json()["data"]
    assert emp["employee_code"] == "E001"
    # Non-sensitive view must NOT expose decrypted secrets.
    assert "national_id" not in emp
    assert "base_salary" not in emp

    reader = auth_header(perms=["employee:read"])
    got = await client.get(f"{API}/employees/{emp['id']}", headers=reader)
    assert got.status_code == 200
    assert got.json()["data"]["full_name"] == "Nguyen Van A"


async def test_sensitive_fields_encrypted_at_rest_and_decryptable(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    writer = auth_header(perms=["employee:write"])
    created = await client.post(f"{API}/employees", json=_emp_payload(), headers=writer)
    emp_id = created.json()["data"]["id"]

    # At rest: the column holds ciphertext bytes, not the plaintext.
    row = (await db_session.execute(select(Employee).where(Employee.id == emp_id))).scalar_one()
    assert isinstance(row.enc_national_id, (bytes, bytearray))
    assert b"012345678901" not in bytes(row.enc_national_id)
    assert decrypt_optional(row.enc_national_id) == "012345678901"

    # Via the sensitive endpoint (requires salary:view_sensitive), it decrypts.
    viewer = auth_header(perms=["salary:view_sensitive"])
    sens = await client.get(f"{API}/employees/{emp_id}/sensitive", headers=viewer)
    assert sens.status_code == 200, sens.text
    data = sens.json()["data"]
    assert data["national_id"] == "012345678901"
    assert data["bank_account"] == "1234567890"
    assert data["base_salary"] == "25000000.00"


async def test_sensitive_endpoint_forbidden_without_permission(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    writer = auth_header(perms=["employee:write"])
    created = await client.post(f"{API}/employees", json=_emp_payload(), headers=writer)
    emp_id = created.json()["data"]["id"]
    # employee:read is not enough to decrypt sensitive data.
    resp = await client.get(
        f"{API}/employees/{emp_id}/sensitive", headers=auth_header(perms=["employee:read"])
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_duplicate_employee_code_conflict(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    writer = auth_header(perms=["employee:write"])
    assert (
        await client.post(f"{API}/employees", json=_emp_payload(), headers=writer)
    ).status_code == 201
    dup = await client.post(
        f"{API}/employees",
        json=_emp_payload(full_name="Nguyen Van B"),
        headers=writer,
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "CONFLICT"


# --------------------------------------------------------------------------- #
# RBAC enforcement                                                            #
# --------------------------------------------------------------------------- #
async def test_list_requires_read_permission(
    client: AsyncClient, auth_header: HeaderFactory
) -> None:
    # Authenticated but lacking employee:read -> 403.
    resp = await client.get(f"{API}/employees", headers=auth_header(perms=["payroll:read"]))
    assert resp.status_code == 403


async def test_create_requires_write_permission(
    client: AsyncClient, auth_header: HeaderFactory
) -> None:
    resp = await client.post(
        f"{API}/employees", json=_emp_payload(), headers=auth_header(perms=["employee:read"])
    )
    assert resp.status_code == 403


async def test_endpoints_require_authentication(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/employees")).status_code == 401


# --------------------------------------------------------------------------- #
# Pagination + filtering                                                      #
# --------------------------------------------------------------------------- #
async def test_list_pagination_and_filter(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    writer = auth_header(perms=["employee:write"])
    for i in range(5):
        await client.post(
            f"{API}/employees",
            json=_emp_payload(employee_code=f"E10{i}", full_name=f"Tester {i}", national_id=None),
            headers=writer,
        )
    reader = auth_header(perms=["employee:read"])

    page1 = await client.get(f"{API}/employees?page=1&size=2", headers=reader)
    assert page1.status_code == 200
    body = page1.json()
    assert len(body["data"]) == 2
    assert body["meta"]["total"] == 5
    assert body["meta"]["pages"] == 3

    # Name search via trigram ILIKE.
    filtered = await client.get(f"{API}/employees?q=Tester 3", headers=reader)
    assert filtered.json()["meta"]["total"] == 1


# --------------------------------------------------------------------------- #
# Blind-index search (service/repository level)                               #
# --------------------------------------------------------------------------- #
async def test_blind_index_exact_match_search(db_session: AsyncSession) -> None:
    actor = CurrentUser(id=1, perms={"employee:write"})
    svc = EmployeeService(db_session)
    emp = await svc.create(
        EmployeeCreate(employee_code="E900", full_name="Tran Thi C", national_id="098765432100"),
        actor,
        None,
    )
    found = await EmployeeRepository(db_session).find_by_national_id_index(
        blind_index("098765432100")
    )
    assert found is not None and found.id == emp.id
    # A different value does not match.
    assert (
        await EmployeeRepository(db_session).find_by_national_id_index(blind_index("000000000000"))
    ) is None


# --------------------------------------------------------------------------- #
# Soft delete                                                                 #
# --------------------------------------------------------------------------- #
async def test_soft_delete_hides_employee(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    writer = auth_header(perms=["employee:write"])
    created = await client.post(f"{API}/employees", json=_emp_payload(), headers=writer)
    emp_id = created.json()["data"]["id"]

    assert (await client.delete(f"{API}/employees/{emp_id}", headers=writer)).status_code == 204
    # Subsequent fetch returns 404 (soft-deleted rows are filtered out).
    gone = await client.get(
        f"{API}/employees/{emp_id}", headers=auth_header(perms=["employee:read"])
    )
    assert gone.status_code == 404


# --------------------------------------------------------------------------- #
# Dynamic profile: validation + encryption masking                           #
# --------------------------------------------------------------------------- #
async def _make_profile_field(
    session: AsyncSession, *, encrypted: bool, required: bool = False
) -> None:
    cat = ProfileCategory(code="PERSONAL", name="Personal", sort_order=1)
    session.add(cat)
    await session.flush()
    session.add(
        ProfileField(
            category_id=cat.id,
            field_key="secret_note",
            label="Secret note",
            data_type="TEXT",
            is_required=required,
            is_encrypted=encrypted,
            is_active=True,
        )
    )
    await session.flush()


async def test_dynamic_profile_required_validation(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    await _make_profile_field(db_session, encrypted=False, required=True)
    writer = auth_header(perms=["employee:write"])
    emp_id = (await client.post(f"{API}/employees", json=_emp_payload(), headers=writer)).json()[
        "data"
    ]["id"]

    # Missing the required field -> 422 validation error with field detail.
    bad = await client.put(f"{API}/employees/{emp_id}/profile", json={"data": {}}, headers=writer)
    assert bad.status_code == 422
    assert "secret_note" in bad.json()["error"]["details"]


async def test_dynamic_profile_encrypted_field_is_masked(
    db_session: AsyncSession, client: AsyncClient, auth_header: HeaderFactory
) -> None:
    await _make_profile_field(db_session, encrypted=True)
    writer = auth_header(perms=["employee:write"])
    emp_id = (await client.post(f"{API}/employees", json=_emp_payload(), headers=writer)).json()[
        "data"
    ]["id"]

    # Save: writer has employee:write but NOT salary:view_sensitive -> response masked.
    saved = await client.put(
        f"{API}/employees/{emp_id}/profile",
        json={"data": {"secret_note": "top-secret"}},
        headers=writer,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["data"]["secret_note"] == "***"

    # Reader without sensitive perm also sees it masked.
    masked = await client.get(
        f"{API}/employees/{emp_id}/profile", headers=auth_header(perms=["employee:read"])
    )
    assert masked.json()["data"]["data"]["secret_note"] == "***"

    # Viewer WITH salary:view_sensitive sees the decrypted value.
    revealed = await client.get(
        f"{API}/employees/{emp_id}/profile",
        headers=auth_header(perms=["employee:read", "salary:view_sensitive"]),
    )
    assert revealed.json()["data"]["data"]["secret_note"] == "top-secret"
