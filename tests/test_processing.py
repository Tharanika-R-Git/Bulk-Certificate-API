"""Tests for the recipient processing core (Celery-free)."""
from __future__ import annotations

from datetime import date

import pytest

from app.db.enums import JobStatus, RecipientStatus
from app.db.models import CertificateRecipient
from app.repositories import jobs as jobs_repo
from app.repositories import recipients as recipients_repo
from app.schemas.jobs import RecipientInput
from app.services import job_service
from app.services.pdf_generator import CertificateGenerator
from app.services.processing import (
    Outcome,
    PermanentError,
    process_recipient,
)
from app.services.storage import build_storage

LOCK = 300
MAX_RETRIES = 2


def _make_job(db, recipients):
    created = job_service.create_job(
        db,
        event_name="Event",
        issuer_name="Issuer",
        issue_date=date(2026, 1, 1),
        recipients=[RecipientInput(**r) for r in recipients],
    )
    ids = [
        row.id
        for row in db.query(CertificateRecipient)
        .filter(CertificateRecipient.job_id == created.job_id)
        .order_by(CertificateRecipient.certificate_number)
        .all()
    ]
    return created.job_id, ids


class FailingGenerator(CertificateGenerator):
    """Raises for recipients whose name matches ``fail_name``."""

    def __init__(self, fail_name: str, error: Exception):
        self._fail_name = fail_name
        self._error = error

    def render(self, data):  # type: ignore[override]
        if data.recipient_name == self._fail_name:
            raise self._error
        return super().render(data)


def _run(db, job_id, rid, generator=None):
    return process_recipient(
        db,
        job_id,
        rid,
        generator=generator or CertificateGenerator(),
        storage=build_storage(),
        lock_timeout_seconds=LOCK,
        max_retries=MAX_RETRIES,
    )


def test_successful_processing_completes_job(db, storage):
    job_id, [rid] = _make_job(db, [{"name": "A", "email": "a@x.com", "certificate_number": "C1"}])
    outcome = _run(db, job_id, rid)
    assert outcome is Outcome.SUCCESS

    recipient = recipients_repo.get(db, rid)
    assert recipient.status == RecipientStatus.SUCCESS.value
    assert recipient.file_key == f"jobs/{job_id}/certificates/{rid}.pdf"
    assert storage.exists(recipient.file_key)

    job = jobs_repo.get(db, job_id)
    assert job.status == JobStatus.COMPLETED.value
    assert job.success_count == 1
    assert job.completed_at is not None


def test_processing_is_idempotent(db):
    job_id, [rid] = _make_job(db, [{"name": "A", "email": "a@x.com", "certificate_number": "C1"}])
    assert _run(db, job_id, rid) is Outcome.SUCCESS
    # Duplicate delivery of the same task must be a no-op.
    assert _run(db, job_id, rid) is Outcome.SKIPPED
    job = jobs_repo.get(db, job_id)
    assert job.success_count == 1  # not double counted


def test_claim_prevents_concurrent_processing(db):
    job_id, [rid] = _make_job(db, [{"name": "A", "email": "a@x.com", "certificate_number": "C1"}])
    assert recipients_repo.claim(db, rid, lock_timeout_seconds=LOCK) is True
    db.commit()
    # A second worker cannot claim a freshly-locked recipient.
    assert recipients_repo.claim(db, rid, lock_timeout_seconds=LOCK) is False


def test_one_failure_does_not_block_others(db):
    job_id, ids = _make_job(
        db,
        [
            {"name": "Good", "email": "g@x.com", "certificate_number": "C1"},
            {"name": "Bad", "email": "b@x.com", "certificate_number": "C2"},
        ],
    )
    gen = FailingGenerator("Bad", PermanentError("boom"))
    for rid in ids:
        _run(db, job_id, rid, generator=gen)

    job = jobs_repo.get(db, job_id)
    assert job.status == JobStatus.COMPLETED_WITH_ERRORS.value
    assert job.success_count == 1
    assert job.failure_count == 1


def test_permanent_error_is_not_retried(db):
    job_id, [rid] = _make_job(db, [{"name": "Bad", "email": "b@x.com", "certificate_number": "C1"}])
    gen = FailingGenerator("Bad", PermanentError("invalid"))
    assert _run(db, job_id, rid, generator=gen) is Outcome.FAILED_PERMANENT
    recipient = recipients_repo.get(db, rid)
    assert recipient.status == RecipientStatus.FAILED.value
    assert recipient.retry_count == 0  # never retried
    assert "invalid data" in recipient.error_message


def test_transient_failure_retries_then_exhausts(db):
    job_id, [rid] = _make_job(db, [{"name": "Bad", "email": "b@x.com", "certificate_number": "C1"}])
    gen = FailingGenerator("Bad", RuntimeError("temporary"))

    assert _run(db, job_id, rid, generator=gen) is Outcome.RETRY
    assert recipients_repo.get(db, rid).retry_count == 1
    assert recipients_repo.get(db, rid).status == RecipientStatus.PENDING.value

    assert _run(db, job_id, rid, generator=gen) is Outcome.RETRY
    assert recipients_repo.get(db, rid).retry_count == 2

    # Retry budget (MAX_RETRIES=2) exhausted on the third attempt.
    assert _run(db, job_id, rid, generator=gen) is Outcome.EXHAUSTED
    recipient = recipients_repo.get(db, rid)
    assert recipient.status == RecipientStatus.FAILED.value
    job = jobs_repo.get(db, job_id)
    assert job.status == JobStatus.FAILED.value


def test_transient_then_success_recovers(db):
    """A recipient that fails once then succeeds ends up SUCCESS."""
    job_id, [rid] = _make_job(db, [{"name": "Flaky", "email": "f@x.com", "certificate_number": "C1"}])

    class FlakyGenerator(CertificateGenerator):
        def __init__(self):
            self.calls = 0

        def render(self, data):  # type: ignore[override]
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient")
            return super().render(data)

    gen = FlakyGenerator()
    assert _run(db, job_id, rid, generator=gen) is Outcome.RETRY
    assert _run(db, job_id, rid, generator=gen) is Outcome.SUCCESS
    assert jobs_repo.get(db, job_id).status == JobStatus.COMPLETED.value


def test_unknown_recipient_is_skipped(db):
    import uuid

    job_id, [rid] = _make_job(db, [{"name": "A", "email": "a@x.com", "certificate_number": "C1"}])
    assert _run(db, job_id, uuid.uuid4()) is Outcome.SKIPPED
