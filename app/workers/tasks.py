"""Celery tasks: thin wrappers around the testable processing core."""
from __future__ import annotations

import uuid

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.database import get_sessionmaker
from app.repositories import outbox as outbox_repo
from app.repositories import recipients as recipients_repo
from app.services.pdf_generator import CertificateGenerator
from app.services.processing import Outcome, process_recipient
from app.services.storage import build_storage
from app.workers.celery_app import celery_app

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)

_generator = CertificateGenerator()


@celery_app.task(
    bind=True,
    name="app.workers.tasks.generate_certificate",
    max_retries=None,  # retry budget is enforced in the processing core
)
def generate_certificate(self, job_id: str, recipient_id: str) -> str:
    """Generate one certificate. Receives only ids (never the payload)."""
    storage = build_storage()
    session = get_sessionmaker()()
    try:
        outcome = process_recipient(
            session,
            uuid.UUID(job_id),
            uuid.UUID(recipient_id),
            generator=_generator,
            storage=storage,
            lock_timeout_seconds=settings.recipient_lock_timeout_seconds,
            max_retries=settings.max_retries,
        )
    finally:
        session.close()

    if outcome is Outcome.RETRY:
        # Exponential backoff: base * 2**attempt (jittered by Celery).
        delay = settings.retry_backoff_base_seconds * (2 ** self.request.retries)
        raise self.retry(countdown=delay)
    return outcome.value


@celery_app.task(name="app.workers.tasks.dispatch_outbox")
def dispatch_outbox() -> int:
    """Publish any unpublished outbox rows to the broker (recovery net)."""
    session = get_sessionmaker()()
    published = 0
    try:
        entries = outbox_repo.fetch_unpublished(session)
        for entry in entries:
            generate_certificate.delay(str(entry.job_id), str(entry.recipient_id))
            outbox_repo.mark_published(session, entry.id)
            published += 1
        session.commit()
    finally:
        session.close()
    if published:
        logger.info("dispatched outbox entries", extra={"extra": {"count": published}})
    return published


@celery_app.task(name="app.workers.tasks.reap_stale_recipients")
def reap_stale_recipients() -> int:
    """Recover recipients abandoned by crashed workers and re-enqueue them."""
    session = get_sessionmaker()()
    try:
        ids = recipients_repo.reap_stale(
            session, lock_timeout_seconds=settings.recipient_lock_timeout_seconds
        )
        session.commit()
        for rid in ids:
            recipient = recipients_repo.get(session, rid)
            if recipient is not None:
                generate_certificate.delay(str(recipient.job_id), str(rid))
    finally:
        session.close()
    if ids:
        logger.warning("reaped stale recipients", extra={"extra": {"count": len(ids)}})
    return len(ids)
