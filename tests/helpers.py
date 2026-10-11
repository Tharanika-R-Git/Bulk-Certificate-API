"""Test helpers for driving processing without a live Celery worker."""
from __future__ import annotations

import uuid

from app.db.database import get_sessionmaker
from app.db.enums import RecipientStatus
from app.db.models import CertificateRecipient
from app.services.pdf_generator import CertificateGenerator
from app.services.processing import Outcome, process_recipient
from app.services.storage import build_storage


def drive_processing(job_id: uuid.UUID, *, generator: CertificateGenerator | None = None) -> None:
    """Process every non-terminal recipient of a job to completion.

    Mimics what Celery workers would do, including bounded retries, so API-level
    tests can observe success/failure states deterministically.
    """
    gen = generator or CertificateGenerator()
    storage = build_storage()
    session = get_sessionmaker()()
    try:
        for _ in range(10):  # bounded loop to drain retries
            pending = (
                session.query(CertificateRecipient)
                .filter(
                    CertificateRecipient.job_id == job_id,
                    CertificateRecipient.status.in_(
                        [RecipientStatus.PENDING.value, RecipientStatus.PROCESSING.value]
                    ),
                )
                .all()
            )
            if not pending:
                break
            for recipient in pending:
                process_recipient(
                    session,
                    job_id,
                    recipient.id,
                    generator=gen,
                    storage=storage,
                    lock_timeout_seconds=300,
                    max_retries=2,
                )
    finally:
        session.close()


__all__ = ["drive_processing", "Outcome"]
