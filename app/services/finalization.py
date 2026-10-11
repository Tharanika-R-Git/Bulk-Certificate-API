"""Job finalization: decide a job's terminal status from recipient states.

Called after every recipient reaches a terminal state. The job row is locked
(``SELECT ... FOR UPDATE``) so that when the last two recipients finish on
different workers at the same time, only one transaction finalizes the job and
counters cannot be corrupted.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.enums import JobStatus, RecipientStatus, TERMINAL_JOB_STATUSES
from app.repositories import jobs as jobs_repo
from app.repositories import recipients as recipients_repo

logger = get_logger(__name__)


def maybe_finalize_job(session: Session, job_id: uuid.UUID) -> JobStatus | None:
    """Finalize the job if all its recipients are terminal.

    Returns the terminal :class:`JobStatus` if finalization happened (or the job
    was already terminal), else ``None`` while work remains.
    """
    job = jobs_repo.get_for_update(session, job_id)
    if job is None:
        return None
    if JobStatus(job.status) in TERMINAL_JOB_STATUSES:
        return JobStatus(job.status)

    counts = recipients_repo.status_counts(session, job_id)
    success = counts.get(RecipientStatus.SUCCESS.value, 0)
    failed = counts.get(RecipientStatus.FAILED.value, 0)
    pending = counts.get(RecipientStatus.PENDING.value, 0)
    processing = counts.get(RecipientStatus.PROCESSING.value, 0)

    if pending or processing:
        return None  # not all recipients terminal yet

    total = success + failed
    if total == 0:
        final = JobStatus.FAILED
    elif failed == 0:
        final = JobStatus.COMPLETED
    elif success == 0:
        final = JobStatus.FAILED
    else:
        final = JobStatus.COMPLETED_WITH_ERRORS

    # Reconcile denormalized counters with the recipient source of truth.
    job.success_count = success
    job.failure_count = failed
    job.status = final.value
    jobs_repo.set_status(session, job_id, final, completed=True)

    logger.info(
        "job finalized",
        extra={"extra": {"job_id": str(job_id), "status": final.value,
                         "success": success, "failed": failed}},
    )
    return final
