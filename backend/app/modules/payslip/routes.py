"""Payslip API routes (docs/03c §3.5).

Authorization:
  * payroll:lock  -> prepare payslips for a locked run
  * authenticated -> view / confirm / dispute *own* payslips (ownership checked
    in the service); payroll:read can view any.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.pagination import Envelope
from app.core.rbac import CurrentUser, CurrentUserDep, require_perm
from app.core.storage import storage
from app.db.session import get_db
from app.modules.payslip.schemas import FeedbackRequest, PayslipOut
from app.modules.payslip.service import PayslipService

router = APIRouter(prefix="/payslips", tags=["payslips"])

logger = get_logger("payslip.routes")
DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.post("/runs/{run_id}/prepare", response_model=Envelope[dict])
async def prepare(
    run_id: int,
    db: DbDep,
    _: CurrentUser = require_perm("payroll:lock"),
) -> Envelope[dict]:
    """Create PENDING payslips for every item of a locked run."""
    created = await PayslipService(db).prepare_for_run(run_id)
    return Envelope(data={"run_id": run_id, "created": created})


@router.get("/me", response_model=Envelope[list[PayslipOut]])
async def my_payslips(db: DbDep, user: CurrentUserDep) -> Envelope[list[PayslipOut]]:
    rows = await PayslipService(db).list_for_user(user)
    return Envelope(data=[PayslipOut.model_validate(p) for p in rows])


@router.get("/{payslip_id}", response_model=Envelope[PayslipOut])
async def get_payslip(payslip_id: int, db: DbDep, user: CurrentUserDep) -> Envelope[PayslipOut]:
    payslip = await PayslipService(db).get_for_view(payslip_id, user)
    return Envelope(data=PayslipOut.model_validate(payslip))


@router.post("/{payslip_id}/confirm", response_model=Envelope[PayslipOut])
async def confirm_payslip(payslip_id: int, db: DbDep, user: CurrentUserDep) -> Envelope[PayslipOut]:
    """Employee confirms the figures; this kicks off PDF generation + email."""
    payslip = await PayslipService(db).confirm(payslip_id, user)
    # Fire the async pipeline (PDF -> email). Best-effort: a broker hiccup must
    # not fail the confirmation; the run item is already CONFIRMED in the txn.
    try:
        from app.workers.pdf_tasks import gen_payslip_pdf

        gen_payslip_pdf.delay(payslip.run_item_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("payslip_enqueue_failed", payslip_id=payslip_id, error=str(exc))
    return Envelope(data=PayslipOut.model_validate(payslip))


@router.post("/{payslip_id}/feedback", response_model=Envelope[PayslipOut])
async def feedback_payslip(
    payslip_id: int, payload: FeedbackRequest, db: DbDep, user: CurrentUserDep
) -> Envelope[PayslipOut]:
    payslip = await PayslipService(db).reject(payslip_id, payload.reason, user)
    return Envelope(data=PayslipOut.model_validate(payslip))


@router.get("/{payslip_id}/download")
async def download_payslip(
    payslip_id: int,
    request: Request,
    db: DbDep,
    user: CurrentUserDep,
) -> Response:
    """Stream the (CCCD-encrypted) payslip PDF from object storage."""
    key = await PayslipService(db).file_key(payslip_id, user)
    content = storage.get_object(key)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="payslip_{payslip_id}.pdf"'},
    )
