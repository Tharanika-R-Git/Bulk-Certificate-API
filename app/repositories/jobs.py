"""Data-access helpers for :class:`CertificateJob`."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.enums import JobStatus
from app.db.models import CertificateJob


def get(session: Session, job_id: uuid.UUID) -> CertificateJob | None:
    return session.get(CertificateJob, job_id)


def get_for_update(session: Session, job_id: uuid.UUID) -> CertificateJob | None:
    """Row-lock the job so concurrent finalizers cannot race.

    ``with_for_update`` is a no-op on SQLite (single writer) but provides the
    required serialization on PostgreSQL.
    """
    stmt = select(CertificateJob).where(CertificateJob.id == job_id).with_for_update()
    return session.execute(stmt).scalar_one_or_none()


def increment_success(session: Session, job_id: uuid.UUID) -> None:
    session.execute(
        update(CertificateJob)
        .where(CertificateJob.id == job_id)
        .values(success_count=CertificateJob.success_count + 1)
    )


def increment_failure(session: Session, job_id: uuid.UUID) -> None:
    session.execute(
        update(CertificateJob)
        .where(CertificateJob.id == job_id)
        .values(failure_count=CertificateJob.failure_count + 1)
    )


def mark_processing_if_queued(session: Session, job_id: uuid.UUID) -> None:
    """Move QUEUED -> PROCESSING when the first recipient starts."""
    session.execute(
        update(CertificateJob)
        .where(CertificateJob.id == job_id, CertificateJob.status == JobStatus.QUEUED.value)
        .values(status=JobStatus.PROCESSING.value)
    )


def set_status(
    session: Session,
    job_id: uuid.UUID,
    status: JobStatus,
    *,
    completed: bool = False,
) -> None:
    values: dict[str, object] = {"status": status.value}
    if completed:
        values["completed_at"] = datetime.now(timezone.utc)
    session.execute(update(CertificateJob).where(CertificateJob.id == job_id).values(**values))
