"""SQLAlchemy 2.x ORM models.

Design notes
------------
* ``Uuid`` primary keys are generated application-side (``uuid4``) so creation
  does not depend on a DB round-trip and works identically on PostgreSQL and
  the SQLite test database.
* Certificate numbers are unique **per job** (``uq_recipient_job_certno``), not
  globally: the same external certificate number may legitimately be reused
  across unrelated events, but must be unique within a single batch so results
  stay unambiguous.
* ``CertificateJob`` carries denormalized counters for fast status reads, but
  the ``CertificateRecipient`` rows remain the source of truth; counters are
  only ever mutated with atomic ``col = col + 1`` SQL inside the same
  transaction that moves a recipient to a terminal state.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db.enums import JobStatus, RecipientStatus


class Base(DeclarativeBase):
    pass


class CertificateJob(Base):
    __tablename__ = "certificate_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    issuer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[JobStatus] = mapped_column(
        String(32), nullable=False, default=JobStatus.QUEUED.value, index=True
    )

    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    recipients: Mapped[list["CertificateRecipient"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("total_count >= 0", name="ck_job_total_nonneg"),
        CheckConstraint("success_count >= 0", name="ck_job_success_nonneg"),
        CheckConstraint("failure_count >= 0", name="ck_job_failure_nonneg"),
    )


class CertificateRecipient(Base):
    __tablename__ = "certificate_recipients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("certificate_jobs.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    certificate_number: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    status: Mapped[RecipientStatus] = mapped_column(
        String(32), nullable=False, default=RecipientStatus.PENDING.value
    )
    file_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Set when a worker claims the recipient; used to detect abandoned work.
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    job: Mapped[CertificateJob] = relationship(back_populates="recipients")

    __table_args__ = (
        Index("ix_recipient_job_id", "job_id"),
        Index("ix_recipient_job_status", "job_id", "status"),
        # Certificate numbers are unique within a job, but only among recipients
        # that hold a real certificate slot (not validation-rejected rows). A
        # batch's duplicate numbers are all rejected to FAILED, so excluding
        # FAILED keeps those display rows from colliding on the index.
        Index(
            "uq_recipient_job_certno",
            "job_id",
            "certificate_number",
            unique=True,
            sqlite_where=text("status != 'FAILED'"),
            postgresql_where=text("status != 'FAILED'"),
        ),
    )


class OutboxEntry(Base):
    """Transactional outbox row.

    One row is written **in the same transaction** as the recipient it refers
    to. A background dispatcher publishes unpublished rows to the broker and
    marks them published, guaranteeing that a valid recipient is eventually
    enqueued even if the broker was unreachable at request time.
    """

    __tablename__ = "outbox_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("certificate_jobs.id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("certificate_recipients.id", ondelete="CASCADE"), nullable=False
    )
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_outbox_unpublished", "published"),
    )
