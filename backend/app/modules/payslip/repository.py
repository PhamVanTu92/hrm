"""Data-access for the payslip module."""

from __future__ import annotations

from sqlalchemy import select

from app.db.repository import BaseRepository
from app.modules.payslip.models import FileAttachment, Payslip


class PayslipRepository(BaseRepository[Payslip]):
    model = Payslip

    async def get_by_run_item(self, run_item_id: int) -> Payslip | None:
        return await self.get_or_none_by(run_item_id=run_item_id)

    async def list_for_employee(self, employee_id: int) -> list[Payslip]:
        stmt = (
            select(Payslip)
            .where(Payslip.employee_id == employee_id)
            .order_by(Payslip.period.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())


class FileAttachmentRepository(BaseRepository[FileAttachment]):
    model = FileAttachment
