"""Data-access helpers for the transactional outbox."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import OutboxEntry


def add(session: Session, job_id: uuid.UUID, recipient_id: uuid.UUID) -> OutboxEntry:
    entry = OutboxEntry(job_id=job_id, recipient_id=recipient_id, published=False)
    session.add(entry)
    return entry


def mark_published(session: Session, entry_id: uuid.UUID) -> None:
    session.execute(
        update(OutboxEntry)
        .where(OutboxEntry.id == entry_id)
        .values(published=True, published_at=datetime.now(timezone.utc))
    )


def fetch_unpublished(session: Session, *, limit: int = 500) -> list[OutboxEntry]:
    """Return unpublished outbox rows, skipping any locked by another dispatcher.

    ``with_for_update(skip_locked=True)`` lets multiple dispatcher runs operate
    concurrently without double-handling rows on PostgreSQL; on SQLite it is a
    harmless no-op.
    """
    stmt = (
        select(OutboxEntry)
        .where(OutboxEntry.published.is_(False))
        .order_by(OutboxEntry.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(session.execute(stmt).scalars().all())
