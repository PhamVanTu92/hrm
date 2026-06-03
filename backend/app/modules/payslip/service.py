"""Payslip use-cases: prepare on lock, confirm/reject, and the
render -> encrypt -> upload pipeline (docs/03c §3.5).

Heavy native libraries (WeasyPrint, pikepdf) are imported lazily inside the
generation step so the rest of the module imports without them (they live in
the Docker image's optional ``[pdf]`` extra).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_optional
from app.core.exceptions import ConflictError, NotFoundError, PermissionDenied
from app.core.logging import get_logger
from app.core.rbac import CurrentUser
from app.core.storage import storage
from app.modules.employee.models import Employee
from app.modules.payroll.models import NET_VAR
from app.modules.payroll.repository import PeriodRepository, RunItemRepository, RunRepository
from app.modules.payslip.models import (
    EmailStatus,
    FileAttachment,
    FileKind,
    Payslip,
    PayslipStatus,
)
from app.modules.payslip.repository import FileAttachmentRepository, PayslipRepository

logger = get_logger("payslip.service")

_TEMPLATE_DIR = Path(__file__).parent / "templates"


@lru_cache(maxsize=1)
def _jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_payslip_html(*, employee_code: str, full_name: str, period: str, result: dict) -> str:
    """Render the payslip HTML from a run item's result map."""
    net = float(result.get(NET_VAR, 0) or 0)
    lines = sorted((k, float(v)) for k, v in result.items() if k != NET_VAR)
    return (
        _jinja_env()
        .get_template("payslip.html")
        .render(
            employee_code=employee_code,
            full_name=full_name,
            period=period,
            lines=lines,
            net=net,
            pwd_hint="6 số cuối CCCD",  # noqa: S106 - UI hint text, not a secret
        )
    )


def _render_pdf(html: str) -> bytes:
    """HTML -> PDF via WeasyPrint (lazy import; needs the [pdf] extra)."""
    from weasyprint import HTML  # noqa: PLC0415 - heavy, optional dependency

    return HTML(string=html).write_pdf()


def _encrypt_pdf(pdf_bytes: bytes, password: str) -> bytes:
    """Password-protect a PDF with AES-256 via pikepdf (lazy import)."""
    import pikepdf  # noqa: PLC0415 - heavy, optional dependency

    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        out = io.BytesIO()
        pdf.save(
            out,
            encryption=pikepdf.Encryption(user=password, owner=password, R=6),
        )
        return out.getvalue()


class PayslipService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.payslips = PayslipRepository(session)
        self.files = FileAttachmentRepository(session)
        self.run_items = RunItemRepository(session)
        self.runs = RunRepository(session)
        self.periods = PeriodRepository(session)

    # ----------------------------------------------------------------- #
    # Prepare (on payroll lock)                                         #
    # ----------------------------------------------------------------- #
    async def prepare_for_run(self, run_id: int) -> int:
        """Create a PENDING payslip per run item (idempotent). Returns count."""
        run = await self.runs.get(run_id)
        if run is None:
            raise NotFoundError("Không tìm thấy bảng tính lương")
        period = await self.periods.get(run.period_id)
        assert period is not None

        items = await self.run_items.list_for_run(run_id)
        created = 0
        for item in items:
            if await self.payslips.get_by_run_item(item.id):
                continue
            self.session.add(
                Payslip(
                    run_item_id=item.id,
                    employee_id=item.employee_id,
                    period=period.code,
                    status=PayslipStatus.PENDING,
                )
            )
            created += 1
        await self.session.flush()
        logger.info("payslips_prepared", run_id=run_id, created=created)
        return created

    # ----------------------------------------------------------------- #
    # Employee actions                                                  #
    # ----------------------------------------------------------------- #
    async def confirm(self, payslip_id: int, actor: CurrentUser) -> Payslip:
        payslip = await self._get_owned(payslip_id, actor)
        if payslip.status != PayslipStatus.PENDING:
            raise ConflictError("Phiếu lương không ở trạng thái chờ xác nhận")
        payslip.status = PayslipStatus.CONFIRMED
        payslip.confirmed_at = datetime.now(UTC)
        await self.session.flush()
        return payslip

    async def reject(self, payslip_id: int, reason: str, actor: CurrentUser) -> Payslip:
        payslip = await self._get_owned(payslip_id, actor)
        if payslip.status != PayslipStatus.PENDING:
            raise ConflictError("Phiếu lương không ở trạng thái chờ xác nhận")
        payslip.status = PayslipStatus.REJECTED
        payslip.feedback = reason
        await self.session.flush()
        return payslip

    async def list_for_user(self, actor: CurrentUser) -> list[Payslip]:
        employee_id = await self._employee_id_of(actor)
        if employee_id is None:
            return []
        return await self.payslips.list_for_employee(employee_id)

    async def get_for_view(self, payslip_id: int, actor: CurrentUser) -> Payslip:
        return await self._get_owned(payslip_id, actor)

    # ----------------------------------------------------------------- #
    # Generation pipeline (worker)                                      #
    # ----------------------------------------------------------------- #
    async def generate_and_store(self, run_item_id: int) -> Payslip:
        """Render -> encrypt (CCCD) -> upload to object storage; link the file."""
        payslip = await self.payslips.get_by_run_item(run_item_id)
        if payslip is None:
            raise NotFoundError("Chưa có phiếu lương cho mục này")
        item = await self.run_items.get(run_item_id)
        if item is None:
            raise NotFoundError("Không tìm thấy dòng tính lương")
        employee = await self.session.get(Employee, item.employee_id)
        if employee is None:
            raise NotFoundError("Không tìm thấy nhân viên")

        password = self._pdf_password(employee)
        html = render_payslip_html(
            employee_code=employee.employee_code,
            full_name=employee.full_name,
            period=payslip.period,
            result=item.result,
        )
        pdf_bytes = _render_pdf(html)
        encrypted = _encrypt_pdf(pdf_bytes, password)

        key = f"payslips/{payslip.period}/{employee.employee_code}.pdf"
        storage.put_object(key, encrypted, content_type="application/pdf")

        attachment = FileAttachment(
            kind=FileKind.PAYSLIP,
            entity_type="payroll_run_items",
            entity_id=item.id,
            object_key=key,
            content_type="application/pdf",
            encrypted=True,
            size=len(encrypted),
        )
        await self.files.add(attachment)
        payslip.file_id = attachment.id
        payslip.pwd_hint = "6 số cuối CCCD"  # noqa: S105 - UI hint text, not a secret
        await self.session.flush()
        logger.info("payslip_generated", payslip_id=payslip.id, key=key)
        return payslip

    @staticmethod
    def _pdf_password(employee: Employee) -> str:
        """Last 6 digits of the CCCD; fall back to the employee code."""
        cccd = decrypt_optional(employee.enc_national_id)
        base = cccd or employee.employee_code
        return base[-6:]

    # ----------------------------------------------------------------- #
    # Email status (called by the email task)                           #
    # ----------------------------------------------------------------- #
    async def mark_email_sent(self, payslip_id: int) -> None:
        payslip = await self.payslips.get(payslip_id)
        if payslip is not None:
            payslip.email_status = EmailStatus.SENT
            payslip.sent_at = datetime.now(UTC)
            await self.session.flush()

    async def mark_email_failed(self, payslip_id: int) -> None:
        payslip = await self.payslips.get(payslip_id)
        if payslip is not None:
            payslip.email_status = EmailStatus.FAILED
            payslip.retry_count += 1
            await self.session.flush()

    async def file_key(self, payslip_id: int, actor: CurrentUser) -> str:
        payslip = await self._get_owned(payslip_id, actor)
        if payslip.file_id is None:
            raise NotFoundError("Phiếu lương chưa được tạo file")
        attachment = await self.files.get(payslip.file_id)
        if attachment is None:
            raise NotFoundError("Không tìm thấy file phiếu lương")
        return attachment.object_key

    # ----------------------------------------------------------------- #
    # Ownership                                                         #
    # ----------------------------------------------------------------- #
    async def _employee_id_of(self, actor: CurrentUser) -> int | None:
        if actor.employee_id is not None:
            return actor.employee_id
        emp = (
            await self.session.execute(select(Employee.id).where(Employee.user_id == actor.id))
        ).scalar_one_or_none()
        return emp

    async def _get_owned(self, payslip_id: int, actor: CurrentUser) -> Payslip:
        payslip = await self.payslips.get(payslip_id)
        if payslip is None:
            raise NotFoundError("Không tìm thấy phiếu lương")
        # HR/payroll roles can view any; an employee only their own.
        if actor.has("payroll:read"):
            return payslip
        employee_id = await self._employee_id_of(actor)
        if employee_id != payslip.employee_id:
            raise PermissionDenied("Bạn chỉ được xem phiếu lương của mình")
        return payslip
