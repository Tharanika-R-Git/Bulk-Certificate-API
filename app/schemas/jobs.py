"""Request/response schemas for certificate jobs."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class RecipientInput(BaseModel):
    """One recipient as supplied by the client.

    Fields are typed as plain strings on purpose: semantic validation
    (non-empty name, email format, certificate number, duplicates) happens in
    the validation service so a single bad recipient is *recorded* rather than
    rejecting the whole batch. Only structural problems (missing keys, wrong
    JSON types) are rejected by Pydantic as job-level 422 errors.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = ""
    email: str = ""
    certificate_number: str = ""


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_name: str = Field(min_length=1, max_length=255)
    issuer_name: str = Field(min_length=1, max_length=255)
    issue_date: date
    # min_length=1 rejects empty batches at the job level (422).
    recipients: list[RecipientInput] = Field(min_length=1)


class RejectedRecipient(BaseModel):
    index: int
    certificate_number: str
    error: str


class CreateJobResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    status_url: str
    total_recipients: int
    accepted: int
    rejected: int


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    event_name: str
    issuer_name: str
    issue_date: date
    status: str
    total: int
    processed: int
    success_count: int
    failure_count: int
    progress_percentage: float
    created_at: datetime
    completed_at: datetime | None
