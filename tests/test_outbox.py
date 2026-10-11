"""Tests for the transactional outbox and persistence."""
from __future__ import annotations

from datetime import date

from app.db.database import get_sessionmaker
from app.db.enums import JobStatus
from app.repositories import jobs as jobs_repo
from app.repositories import outbox as outbox_repo
from app.schemas.jobs import RecipientInput
from app.services import job_service


def _create(db, recipients):
    return job_service.create_job(
        db,
        event_name="Event",
        issuer_name="Issuer",
        issue_date=date(2026, 1, 1),
        recipients=[RecipientInput(**r) for r in recipients],
    )


def test_outbox_rows_created_for_valid_recipients(db):
    created = _create(
        db,
        [
            {"name": "A", "email": "a@x.com", "certificate_number": "C1"},
            {"name": "B", "email": "b@x.com", "certificate_number": "C2"},
        ],
    )
    assert created.accepted == 2
    unpublished = outbox_repo.fetch_unpublished(db)
    assert len(unpublished) == 2
    assert {str(e.recipient_id) for e in unpublished} == {str(t.recipient_id) for t in created.pending_tasks}


def test_mark_published_removes_from_unpublished(db):
    created = _create(db, [{"name": "A", "email": "a@x.com", "certificate_number": "C1"}])
    entries = outbox_repo.fetch_unpublished(db)
    assert len(entries) == 1
    outbox_repo.mark_published(db, entries[0].id)
    db.commit()
    assert outbox_repo.fetch_unpublished(db) == []


def test_invalid_only_batch_creates_no_outbox_rows(db):
    created = _create(db, [{"name": "", "email": "bad", "certificate_number": ""}])
    assert created.accepted == 0
    assert outbox_repo.fetch_unpublished(db) == []
    job = jobs_repo.get(db, created.job_id)
    assert job.status == JobStatus.FAILED.value


def test_job_persists_in_a_fresh_session(db):
    """Simulate an application restart: data committed by one session is
    visible to a brand-new session/engine connection."""
    created = _create(db, [{"name": "A", "email": "a@x.com", "certificate_number": "C1"}])
    job_id = created.job_id
    db.close()

    fresh = get_sessionmaker()()
    try:
        job = jobs_repo.get(fresh, job_id)
        assert job is not None
        assert job.event_name == "Event"
        assert len(job.recipients) == 1
    finally:
        fresh.close()
