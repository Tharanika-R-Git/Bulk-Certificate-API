"""Data-access helpers for :class:`CertificateRecipient`."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.enums import RecipientStatus
from app.db.models import CertificateRecipient


def get(session: Session, recipient_id: uuid.UUID) -> CertificateRecipient | None:
    return session.get(CertificateRecipient, recipient_id)


def claim(
    session: Session,
    recipient_id: uuid.UUID,
    *,
    lock_timeout_seconds: int,
) -> bool:
    """Atomically transition a recipient into PROCESSING.

    Succeeds only when the recipient is PENDING, or is PROCESSING but its lock
    is stale (the previous worker crashed). Returns ``True`` when this call won
    the claim. Terminal recipients (SUCCESS/FAILED) can never be re-claimed,
    which is what makes task processing idempotent and safe against duplicate
    deliveries.
    """
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=lock_timeout_seconds)
    result = session.execute(
        update(CertificateRecipient)
        .where(
            CertificateRecipient.id == recipient_id,
            (
                (CertificateRecipient.status == RecipientStatus.PENDING.value)
                | (
                    (CertificateRecipient.status == RecipientStatus.PROCESSING.value)
                    & (CertificateRecipient.locked_at < stale_before)
                )
            ),
        )
        .values(status=RecipientStatus.PROCESSING.value, locked_at=now)
    )
    return result.rowcount == 1


def mark_success(session: Session, recipient_id: uuid.UUID, file_key: str) -> None:
    session.execute(
        update(CertificateRecipient)
        .where(CertificateRecipient.id == recipient_id)
        .values(
            status=RecipientStatus.SUCCESS.value,
            file_key=file_key,
            error_message=None,
            locked_at=None,
        )
    )


def mark_failed(session: Session, recipient_id: uuid.UUID, error_message: str) -> None:
    session.execute(
        update(CertificateRecipient)
        .where(CertificateRecipient.id == recipient_id)
        .values(
            status=RecipientStatus.FAILED.value,
            error_message=error_message[:512],
            locked_at=None,
        )
    )


def release_for_retry(session: Session, recipient_id: uuid.UUID, error_message: str) -> None:
    """Return a recipient to PENDING after a transient failure and bump retries."""
    session.execute(
        update(CertificateRecipient)
        .where(CertificateRecipient.id == recipient_id)
        .values(
            status=RecipientStatus.PENDING.value,
            retry_count=CertificateRecipient.retry_count + 1,
            error_message=error_message[:512],
            locked_at=None,
        )
    )


def count_non_terminal(session: Session, job_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(CertificateRecipient)
        .where(
            CertificateRecipient.job_id == job_id,
            CertificateRecipient.status.in_(
                [RecipientStatus.PENDING.value, RecipientStatus.PROCESSING.value]
            ),
        )
    )
    return int(session.execute(stmt).scalar_one())


def status_counts(session: Session, job_id: uuid.UUID) -> dict[str, int]:
    stmt = (
        select(CertificateRecipient.status, func.count())
        .where(CertificateRecipient.job_id == job_id)
        .group_by(CertificateRecipient.status)
    )
    return {row[0]: int(row[1]) for row in session.execute(stmt).all()}


def list_for_job(
    session: Session, job_id: uuid.UUID, *, limit: int, offset: int
) -> list[CertificateRecipient]:
    stmt = (
        select(CertificateRecipient)
        .where(CertificateRecipient.job_id == job_id)
        .order_by(CertificateRecipient.created_at, CertificateRecipient.id)
        .limit(limit)
        .offset(offset)
    )
    return list(session.execute(stmt).scalars().all())


def count_for_job(session: Session, job_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(CertificateRecipient)
        .where(CertificateRecipient.job_id == job_id)
    )
    return int(session.execute(stmt).scalar_one())


def reap_stale(session: Session, *, lock_timeout_seconds: int) -> list[uuid.UUID]:
    """Reset abandoned PROCESSING recipients to PENDING; return their ids."""
    stale_before = datetime.now(timezone.utc) - timedelta(seconds=lock_timeout_seconds)
    stmt = select(CertificateRecipient.id).where(
        CertificateRecipient.status == RecipientStatus.PROCESSING.value,
        CertificateRecipient.locked_at < stale_before,
    )
    ids = list(session.execute(stmt).scalars().all())
    if ids:
        session.execute(
            update(CertificateRecipient)
            .where(CertificateRecipient.id.in_(ids))
            .values(status=RecipientStatus.PENDING.value, locked_at=None)
        )
    return ids
