"""Certificate job endpoints: create and status."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import job_status_url, progress_percentage
from app.core.config import Settings, get_settings
from app.db.database import get_db
from app.repositories import jobs as jobs_repo
from app.schemas.common import ErrorResponse
from app.schemas.jobs import (
    CreateJobRequest,
    CreateJobResponse,
    JobStatusResponse,
    RejectedRecipient,
)
from app.services import job_service
from app.services.dispatch import publish_pending

router = APIRouter(prefix="/api/v1/certificate-jobs", tags=["jobs"])


@router.post(
    "",
    response_model=CreateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={422: {"model": ErrorResponse}},
)
def create_job(
    payload: CreateJobRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CreateJobResponse:
    # Job-level validation: configurable maximum batch size.
    if len(payload.recipients) > settings.max_batch_size:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"batch size {len(payload.recipients)} exceeds maximum "
            f"of {settings.max_batch_size}",
        )

    created = job_service.create_job(
        db,
        event_name=payload.event_name,
        issuer_name=payload.issuer_name,
        issue_date=payload.issue_date,
        recipients=payload.recipients,
    )

    # Enqueue after commit; failures fall back to the outbox dispatcher.
    publish_pending(created.job_id, created.pending_tasks)

    return CreateJobResponse(
        job_id=created.job_id,
        status=created.status,
        status_url=job_status_url(created.job_id),
        total_recipients=created.total,
        accepted=created.accepted,
        rejected=len(created.rejected),
    )


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)) -> JobStatusResponse:
    job = jobs_repo.get(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

    processed = job.success_count + job.failure_count
    return JobStatusResponse(
        job_id=job.id,
        event_name=job.event_name,
        issuer_name=job.issuer_name,
        issue_date=job.issue_date,
        status=job.status,
        total=job.total_count,
        processed=processed,
        success_count=job.success_count,
        failure_count=job.failure_count,
        progress_percentage=progress_percentage(job.total_count, processed),
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


# Exposed for documentation/testing of the rejected-recipient schema.
__all__ = ["router", "RejectedRecipient"]
