"""Post-commit task publication with outbox bookkeeping.

Called after a job's rows are committed. Attempts to enqueue each valid
recipient immediately for low latency; if the broker is unreachable the failure
is swallowed and the outbox row stays unpublished so the periodic dispatcher
(``dispatch_outbox``) will publish it later. Either way a recipient is never
stranded.
"""
from __future__ import annotations

import uuid

from app.core.logging import get_logger
from app.db.database import get_sessionmaker
from app.repositories import outbox as outbox_repo
from app.services.job_service import PendingTask

logger = get_logger(__name__)


def publish_pending(job_id: uuid.UUID, pending: list[PendingTask]) -> int:
    """Try to enqueue pending tasks now; return how many were published."""
    if not pending:
        return 0

    # Imported lazily so the API module does not hard-depend on Celery at import.
    from app.workers.tasks import generate_certificate

    session = get_sessionmaker()()
    published = 0
    try:
        for task in pending:
            try:
                generate_certificate.delay(str(job_id), str(task.recipient_id))
            except Exception as exc:  # broker down -> leave for outbox dispatcher
                logger.warning(
                    "inline enqueue failed; deferring to outbox dispatcher",
                    extra={"extra": {"recipient_id": str(task.recipient_id), "detail": repr(exc)}},
                )
                continue
            outbox_repo.mark_published(session, task.outbox_id)
            published += 1
        session.commit()
    finally:
        session.close()
    return published
