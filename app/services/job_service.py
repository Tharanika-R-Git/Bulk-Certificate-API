"""Job creation orchestration.

Persists the job, all recipient records (valid and invalid) and one outbox row
per valid recipient inside a single transaction, then reports what needs to be
published to the broker. Enqueuing happens *after* commit (see the API layer),
with the outbox as the recovery net for publish failures.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.enums import JobStatus, RecipientStatus
from app.db.models import CertificateJob, CertificateRecipient
from app.repositories import outbox as outbox_repo
from app.schemas.jobs import RecipientInput
from app.services import validation_service
from app.services.finalization import maybe_finalize_job

logger = get_logger(__name__)


@dataclass
class PendingTask:
    outbox_id: uuid.UUID
    recipient_id: uuid.UUID


@dataclass
class CreatedJob:
    job_id: uuid.UUID
    status: str
    total: int
    accepted: int
    rejected: list[validation_service.RejectedRecipientData]
    pending_tasks: list[PendingTask]


def create_job(
    session: Session,
    *,
    event_name: str,
    issuer_name: str,
    issue_date,
    recipients: list[RecipientInput],
) -> CreatedJob:
    """Validate recipients and persist the job atomically."""
    validation = validation_service.validate_recipients(recipients)

    job = CertificateJob(
        event_name=event_name,
        issuer_name=issuer_name,
        issue_date=issue_date,
        status=JobStatus.QUEUED.value,
        total_count=len(recipients),
    )
    session.add(job)
    session.flush()  # assign job.id

    pending: list[PendingTask] = []

    # Valid recipients -> PENDING + outbox row.
    for v in validation.valid:
        recipient = CertificateRecipient(
            job_id=job.id,
            name=v.name,
            email=v.email,
            certificate_number=v.certificate_number,
            status=RecipientStatus.PENDING.value,
        )
        session.add(recipient)
        session.flush()
        entry = outbox_repo.add(session, job.id, recipient.id)
        session.flush()
        pending.append(PendingTask(outbox_id=entry.id, recipient_id=recipient.id))

    # Invalid recipients -> FAILED immediately (never enqueued).
    for r in validation.rejected:
        session.add(
            CertificateRecipient(
                job_id=job.id,
                name="",
                email="",
                certificate_number=r.certificate_number,
                status=RecipientStatus.FAILED.value,
                error_message=r.error[:512],
            )
        )
    job.failure_count = len(validation.rejected)

    # Flush so the rejected rows are visible to the finalization query below
    # (the session uses autoflush=False).
    session.flush()

    # If nothing is processable, the job is already terminal.
    if not validation.valid:
        maybe_finalize_job(session, job.id)

    session.commit()

    logger.info(
        "job created",
        extra={"extra": {"job_id": str(job.id), "accepted": len(validation.valid),
                         "rejected": len(validation.rejected)}},
    )
    return CreatedJob(
        job_id=job.id,
        status=job.status,
        total=len(recipients),
        accepted=len(validation.valid),
        rejected=validation.rejected,
        pending_tasks=pending,
    )
