"""Recipient results endpoint (paginated)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import certificate_download_url
from app.db.database import get_db
from app.db.enums import RecipientStatus
from app.repositories import jobs as jobs_repo
from app.repositories import recipients as recipients_repo
from app.schemas.common import ErrorResponse
from app.schemas.recipients import PaginatedRecipients, RecipientResult

router = APIRouter(prefix="/api/v1/certificate-jobs", tags=["recipients"])


@router.get(
    "/{job_id}/recipients",
    response_model=PaginatedRecipients,
    responses={404: {"model": ErrorResponse}},
)
def list_recipients(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> PaginatedRecipients:
    if jobs_repo.get(db, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

    total = recipients_repo.count_for_job(db, job_id)
    rows = recipients_repo.list_for_job(
        db, job_id, limit=page_size, offset=(page - 1) * page_size
    )

    items = [
        RecipientResult(
            recipient_id=r.id,
            name=r.name,
            email=r.email,
            certificate_number=r.certificate_number,
            status=r.status,
            error_message=r.error_message,
            download_url=(
                certificate_download_url(job_id, r.id)
                if r.status == RecipientStatus.SUCCESS.value
                else None
            ),
        )
        for r in rows
    ]
    return PaginatedRecipients(items=items, total=total, page=page, page_size=page_size)
