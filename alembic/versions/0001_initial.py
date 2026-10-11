"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "certificate_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_name", sa.String(length=255), nullable=False),
        sa.Column("issuer_name", sa.String(length=255), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("total_count >= 0", name="ck_job_total_nonneg"),
        sa.CheckConstraint("success_count >= 0", name="ck_job_success_nonneg"),
        sa.CheckConstraint("failure_count >= 0", name="ck_job_failure_nonneg"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_certificate_jobs_status", "certificate_jobs", ["status"])

    op.create_table(
        "certificate_recipients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("certificate_number", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("file_key", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["certificate_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recipient_job_id", "certificate_recipients", ["job_id"])
    op.create_index("ix_recipient_job_status", "certificate_recipients", ["job_id", "status"])
    op.create_index(
        "uq_recipient_job_certno",
        "certificate_recipients",
        ["job_id", "certificate_number"],
        unique=True,
        postgresql_where=sa.text("status != 'FAILED'"),
        sqlite_where=sa.text("status != 'FAILED'"),
    )

    op.create_table(
        "outbox_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["certificate_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["certificate_recipients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_unpublished", "outbox_entries", ["published"])


def downgrade() -> None:
    op.drop_index("ix_outbox_unpublished", table_name="outbox_entries")
    op.drop_table("outbox_entries")
    op.drop_index("uq_recipient_job_certno", table_name="certificate_recipients")
    op.drop_index("ix_recipient_job_status", table_name="certificate_recipients")
    op.drop_index("ix_recipient_job_id", table_name="certificate_recipients")
    op.drop_table("certificate_recipients")
    op.drop_index("ix_certificate_jobs_status", table_name="certificate_jobs")
    op.drop_table("certificate_jobs")
