"""Explicit, documented state machines for jobs and recipients.

Recipient lifecycle:
    PENDING ──claim──▶ PROCESSING ──success──▶ SUCCESS   (terminal)
                           │
                           └──permanent failure / retries exhausted──▶ FAILED (terminal)
    (transient failure resets PROCESSING ──▶ PENDING for a bounded number of retries)

A recipient that fails validation at job-creation time is written directly as
FAILED (it is never enqueued).

Job lifecycle:
    QUEUED ──first recipient claimed──▶ PROCESSING ──all recipients terminal──▶
        COMPLETED              (every recipient SUCCESS)
        COMPLETED_WITH_ERRORS  (at least one SUCCESS and at least one FAILED)
        FAILED                 (zero SUCCESS)
"""
from __future__ import annotations

import enum


class RecipientStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


# Recipient states that are final and must never transition again.
TERMINAL_RECIPIENT_STATUSES = frozenset({RecipientStatus.SUCCESS, RecipientStatus.FAILED})

# Job states that are final.
TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED}
)
