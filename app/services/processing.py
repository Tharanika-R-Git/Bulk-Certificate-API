"""Celery-free recipient processing core.

Kept independent of Celery so it can be unit-tested directly with a real
(SQLite) session and mocked PDF/storage layers. The Celery task in
``app.workers.tasks`` is a thin wrapper that translates :class:`Outcome` into
retry/ack behaviour.
"""
from __future__ import annotations

import enum
import uuid

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.enums import TERMINAL_RECIPIENT_STATUSES, RecipientStatus
from app.repositories import jobs as jobs_repo
from app.repositories import recipients as recipients_repo
from app.services.finalization import maybe_finalize_job
from app.services.pdf_generator import CertificateData, CertificateGenerator
from app.services.storage import Storage, certificate_key

logger = get_logger(__name__)


class TransientError(Exception):
    """A failure that is worth retrying (I/O, temporary resource issues)."""


class PermanentError(Exception):
    """A failure that must not be retried (bad data that slipped through)."""


class Outcome(str, enum.Enum):
    SUCCESS = "SUCCESS"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    RETRY = "RETRY"
    EXHAUSTED = "EXHAUSTED"
    SKIPPED = "SKIPPED"


def process_recipient(
    session: Session,
    job_id: uuid.UUID,
    recipient_id: uuid.UUID,
    *,
    generator: CertificateGenerator,
    storage: Storage,
    lock_timeout_seconds: int,
    max_retries: int,
) -> Outcome:
    """Process one recipient idempotently. See module docstring."""
    recipient = recipients_repo.get(session, recipient_id)
    if recipient is None or recipient.job_id != job_id:
        logger.info("recipient not found or job mismatch",
                    extra={"extra": {"job_id": str(job_id), "recipient_id": str(recipient_id)}})
        return Outcome.SKIPPED

    if RecipientStatus(recipient.status) in TERMINAL_RECIPIENT_STATUSES:
        return Outcome.SKIPPED  # already done -> duplicate delivery, ignore

    # Atomically claim; only one worker can win.
    if not recipients_repo.claim(session, recipient_id, lock_timeout_seconds=lock_timeout_seconds):
        session.commit()
        return Outcome.SKIPPED
    jobs_repo.mark_processing_if_queued(session, job_id)
    session.commit()

    # Reload fresh row data after the claim.
    recipient = recipients_repo.get(session, recipient_id)
    assert recipient is not None

    try:
        pdf_bytes = generator.render(
            CertificateData(
                event_name=recipient.job.event_name,
                recipient_name=recipient.name,
                certificate_number=recipient.certificate_number,
                issue_date=recipient.job.issue_date,
                issuer_name=recipient.job.issuer_name,
            )
        )
        key = certificate_key(job_id, recipient_id)
        storage.save(key, pdf_bytes)

        recipients_repo.mark_success(session, recipient_id, key)
        jobs_repo.increment_success(session, job_id)
        session.commit()
        _finalize(session, job_id)
        logger.info("recipient succeeded",
                    extra={"extra": {"job_id": str(job_id), "recipient_id": str(recipient_id)}})
        return Outcome.SUCCESS

    except PermanentError as exc:
        logger.warning("recipient permanent failure",
                       extra={"extra": {"job_id": str(job_id), "recipient_id": str(recipient_id),
                                        "detail": str(exc)}})
        return _fail(session, job_id, recipient_id,
                     "Certificate could not be generated due to invalid data.",
                     Outcome.FAILED_PERMANENT)

    except Exception as exc:  # transient / unexpected -> retry with bound
        session.rollback()
        current = recipients_repo.get(session, recipient_id)
        attempts = current.retry_count if current else 0
        # Internal exception detail is logged only, never stored for the API.
        logger.warning("recipient processing error",
                       extra={"extra": {"job_id": str(job_id), "recipient_id": str(recipient_id),
                                        "attempt": attempts + 1, "detail": repr(exc)}})
        if attempts < max_retries:
            recipients_repo.release_for_retry(
                session, recipient_id, "Temporary error while generating certificate; retrying."
            )
            session.commit()
            return Outcome.RETRY
        return _fail(session, job_id, recipient_id,
                     "Certificate generation failed after multiple attempts.",
                     Outcome.EXHAUSTED)


def _fail(session: Session, job_id: uuid.UUID, recipient_id: uuid.UUID,
          message: str, outcome: Outcome) -> Outcome:
    session.rollback()
    recipients_repo.mark_failed(session, recipient_id, message)
    jobs_repo.increment_failure(session, job_id)
    session.commit()
    _finalize(session, job_id)
    logger.warning("recipient failed",
                   extra={"extra": {"job_id": str(job_id), "recipient_id": str(recipient_id),
                                    "outcome": outcome.value}})
    return outcome


def _finalize(session: Session, job_id: uuid.UUID) -> None:
    maybe_finalize_job(session, job_id)
    session.commit()
