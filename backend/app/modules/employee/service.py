"""Employee use-cases: CRUD with field encryption, sensitive access auditing,
and dynamic profile validation/persistence.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.recorder import record
from app.core.encryption import (
    blind_index,
    decrypt_decimal,
    decrypt_from_json,
    decrypt_optional,
    encrypt_decimal,
    encrypt_for_json,
    encrypt_optional,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.pagination import PageParams
from app.core.rbac import CurrentUser
from app.modules.employee.models import (
    Employee,
    EmployeeDynamicProfile,
    ProfileCategory,
    ProfileField,
)
from app.modules.employee.repository import (
    DynamicProfileRepository,
    EmployeeRepository,
    ProfileFieldRepository,
)
from app.modules.employee.schemas import (
    DynamicProfileOut,
    EmployeeCreate,
    EmployeeFilter,
    EmployeeSensitiveOut,
    EmployeeUpdate,
)

_MASK = "***"


class EmployeeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EmployeeRepository(session)
        self.profiles = DynamicProfileRepository(session)
        self.fields = ProfileFieldRepository(session)

    # ---- CRUD ----

    async def list_employees(
        self, params: PageParams, f: EmployeeFilter
    ) -> tuple[list[Employee], int]:
        return await self.repo.list_page(params, filters=self.repo.build_filters(f))

    async def get(self, employee_id: int) -> Employee:
        emp = await self.repo.get(employee_id)
        if emp is None:
            raise NotFoundError("Không tìm thấy nhân viên")
        return emp

    async def create(self, payload: EmployeeCreate, actor: CurrentUser, ip: str | None) -> Employee:
        if await self.repo.get_by_code(payload.employee_code):
            raise ConflictError("Mã nhân viên đã tồn tại")

        emp = Employee(
            employee_code=payload.employee_code,
            full_name=payload.full_name,
            department_id=payload.department_id,
            position_id=payload.position_id,
            manager_id=payload.manager_id,
            join_date=payload.join_date,
            user_id=payload.user_id,
            created_by=actor.id,
            enc_national_id=encrypt_optional(payload.national_id),
            enc_phone=encrypt_optional(payload.phone),
            enc_bank_account=encrypt_optional(payload.bank_account),
            enc_base_salary=encrypt_decimal(payload.base_salary),
            national_id_bidx=blind_index(payload.national_id) if payload.national_id else None,
        )
        await self.repo.add(emp)
        await record(
            self.session,
            actor_id=actor.id,
            action="CREATE",
            entity="employees",
            entity_id=emp.id,
            new={"employee_code": emp.employee_code, "full_name": emp.full_name},
            ip=ip,
        )
        return emp

    async def update(
        self, employee_id: int, payload: EmployeeUpdate, actor: CurrentUser, ip: str | None
    ) -> Employee:
        emp = await self.get(employee_id)
        old = {"full_name": emp.full_name, "status": emp.status}

        if payload.full_name is not None:
            emp.full_name = payload.full_name
        if payload.department_id is not None:
            emp.department_id = payload.department_id
        if payload.position_id is not None:
            emp.position_id = payload.position_id
        if payload.manager_id is not None:
            emp.manager_id = payload.manager_id
        if payload.status is not None:
            emp.status = payload.status
        if payload.national_id is not None:
            emp.enc_national_id = encrypt_optional(payload.national_id)
            emp.national_id_bidx = blind_index(payload.national_id) if payload.national_id else None
        if payload.phone is not None:
            emp.enc_phone = encrypt_optional(payload.phone)
        if payload.bank_account is not None:
            emp.enc_bank_account = encrypt_optional(payload.bank_account)
        if payload.base_salary is not None:
            emp.enc_base_salary = encrypt_decimal(payload.base_salary)

        emp.updated_by = actor.id
        await self.session.flush()
        await record(
            self.session,
            actor_id=actor.id,
            action="UPDATE",
            entity="employees",
            entity_id=emp.id,
            old=old,
            new={"full_name": emp.full_name, "status": emp.status},
            ip=ip,
        )
        return emp

    async def delete(self, employee_id: int, actor: CurrentUser, ip: str | None) -> None:
        emp = await self.get(employee_id)
        await self.repo.delete(emp)  # soft delete
        await record(
            self.session,
            actor_id=actor.id,
            action="DELETE",
            entity="employees",
            entity_id=employee_id,
            ip=ip,
        )

    # ---- Sensitive (decrypted) access — always audited ----

    async def get_sensitive(
        self, employee_id: int, actor: CurrentUser, ip: str | None
    ) -> EmployeeSensitiveOut:
        emp = await self.get(employee_id)
        await record(
            self.session,
            actor_id=actor.id,
            action="VIEW_SENSITIVE",
            entity="employees",
            entity_id=employee_id,
            ip=ip,
        )
        return EmployeeSensitiveOut(
            national_id=decrypt_optional(emp.enc_national_id),
            phone=decrypt_optional(emp.enc_phone),
            bank_account=decrypt_optional(emp.enc_bank_account),
            base_salary=decrypt_decimal(emp.enc_base_salary),
        )

    # ---- Dynamic field metadata (config) ----

    _VALID_DATA_TYPES = frozenset({"TEXT", "NUMBER", "DATE", "SELECT", "BOOLEAN"})

    async def list_fields(self) -> list[ProfileField]:
        """Active field definitions — drives the dynamic form on the frontend."""
        return await self.fields.active_fields()

    async def create_field(
        self,
        *,
        category_id: int,
        field_key: str,
        label: str,
        data_type: str,
        options: list[str] | None,
        is_required: bool,
        is_encrypted: bool,
    ) -> ProfileField:
        if data_type not in self._VALID_DATA_TYPES:
            raise ValidationError(f"Kiểu dữ liệu không hợp lệ: {data_type}")
        category = await self.session.get(ProfileCategory, category_id)
        if category is None:
            raise NotFoundError("Không tìm thấy nhóm trường")
        if await self.fields.get_or_none_by(category_id=category_id, field_key=field_key):
            raise ConflictError("field_key đã tồn tại trong nhóm")
        if data_type == "SELECT" and not options:
            raise ValidationError("Trường SELECT cần danh sách options")
        field = ProfileField(
            category_id=category_id,
            field_key=field_key,
            label=label,
            data_type=data_type,
            options=options,
            is_required=is_required,
            is_encrypted=is_encrypted,
        )
        return await self.fields.add(field)

    async def list_categories(self) -> list[ProfileCategory]:
        stmt = select(ProfileCategory).order_by(ProfileCategory.sort_order, ProfileCategory.id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def create_category(
        self, *, code: str, name: str, sort_order: int = 0
    ) -> ProfileCategory:
        existing = (
            await self.session.execute(select(ProfileCategory).where(ProfileCategory.code == code))
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError("Mã nhóm đã tồn tại")
        category = ProfileCategory(code=code, name=name, sort_order=sort_order)
        self.session.add(category)
        await self.session.flush()
        return category

    # ---- Dynamic profile ----

    async def get_profile(self, employee_id: int, actor: CurrentUser) -> DynamicProfileOut:
        await self.get(employee_id)  # ensure exists
        profile = await self.profiles.get_for_employee(employee_id)
        fields_by_key = {f.field_key: f for f in await self.fields.active_fields()}
        raw = profile.data if profile else {}
        return DynamicProfileOut(
            employee_id=employee_id,
            data=self._read_profile(raw, fields_by_key, actor),
        )

    async def save_profile(
        self, employee_id: int, data: dict[str, Any], actor: CurrentUser, ip: str | None
    ) -> DynamicProfileOut:
        await self.get(employee_id)
        fields = await self.fields.active_fields()
        fields_by_key = {f.field_key: f for f in fields}
        clean = self._validate_profile(fields, data)
        stored = self._persist_profile(clean, fields_by_key)

        profile = await self.profiles.get_for_employee(employee_id)
        if profile is None:
            profile = EmployeeDynamicProfile(employee_id=employee_id, data=stored)
            await self.profiles.add(profile)
        else:
            profile.data = stored
            await self.session.flush()

        await record(
            self.session,
            actor_id=actor.id,
            action="UPDATE",
            entity="employee_dynamic_profiles",
            entity_id=employee_id,
            ip=ip,
        )
        return DynamicProfileOut(
            employee_id=employee_id,
            data=self._read_profile(stored, fields_by_key, actor),
        )

    # ---- profile helpers ----

    @staticmethod
    def _cast(data_type: str, value: Any) -> Any:
        if data_type == "NUMBER":
            try:
                return float(Decimal(str(value)))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("Không phải số") from exc
        if data_type == "BOOLEAN":
            return bool(value)
        # TEXT / DATE / SELECT kept as string; DATE format checked by validation rule.
        return str(value)

    def _validate_profile(
        self, fields: list[ProfileField], payload: dict[str, Any]
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}
        clean: dict[str, Any] = {}
        for f in fields:
            value = payload.get(f.field_key)
            if f.is_required and (value is None or value == ""):
                errors[f.field_key] = "Bắt buộc nhập"
                continue
            if value is None or value == "":
                continue
            try:
                value = self._cast(f.data_type, value)
            except ValueError:
                errors[f.field_key] = f"Sai kiểu {f.data_type}"
                continue
            if f.data_type == "SELECT" and value not in (f.options or []):
                errors[f.field_key] = "Giá trị không nằm trong danh sách"
                continue
            clean[f.field_key] = value
        if errors:
            raise ValidationError("Hồ sơ không hợp lệ", details=errors)
        return clean

    @staticmethod
    def _persist_profile(
        clean: dict[str, Any], fields_by_key: dict[str, ProfileField]
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in clean.items():
            field = fields_by_key.get(key)
            if field and field.is_encrypted:
                out[key] = encrypt_for_json(str(value))
            else:
                out[key] = value
        return out

    @staticmethod
    def _read_profile(
        data: dict[str, Any], fields_by_key: dict[str, ProfileField], actor: CurrentUser
    ) -> dict[str, Any]:
        can_view = "salary:view_sensitive" in actor.perms
        out: dict[str, Any] = {}
        for key, value in data.items():
            field = fields_by_key.get(key)
            if field and field.is_encrypted:
                out[key] = decrypt_from_json(value) if can_view else _MASK
            else:
                out[key] = value
        return out
