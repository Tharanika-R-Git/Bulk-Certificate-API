"""Certificate download endpoint."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.db.database import get_db
from app.db.enums import RecipientStatus
from app.repositories import recipients as recipients_repo
from app.schemas.common import ErrorResponse
from app.services.storage import ObjectNotFound, Storage

router = APIRouter(prefix="/api/v1/certificate-jobs", tags=["certificates"])


@router.get(
    "/{job_id}/certificates/{recipient_id}",
    responses={
        200: {"content": {"application/pdf": {}}},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def download_certificate(
    job_id: uuid.UUID,
    recipient_id: uuid.UUID,
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    recipient = recipients_repo.get(db, recipient_id)
    # The recipient must exist AND belong to the requested job.
    if recipient is None or recipient.job_id != job_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="certificate not found"
        )

    if recipient.status != RecipientStatus.SUCCESS.value or not recipient.file_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="certificate is not available for this recipient",
        )

    try:
        data = storage.load(recipient.file_key)
    except ObjectNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="certificate file missing"
        )

    # Sanitize the certificate number before putting it in a header.
    safe_cert = "".join(ch for ch in (recipient.certificate_number or "") if ch.isalnum() or ch in "-_")
    filename = f"certificate-{safe_cert or recipient.id}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
