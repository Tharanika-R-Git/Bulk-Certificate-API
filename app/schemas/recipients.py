"""Response schemas for recipient results."""
from __future__ import annotations

import uuid

from pydantic import BaseModel


class RecipientResult(BaseModel):
    recipient_id: uuid.UUID
    name: str
    email: str
    certificate_number: str
    status: str
    error_message: str | None = None
    download_url: str | None = None


class PaginatedRecipients(BaseModel):
    items: list[RecipientResult]
    total: int
    page: int
    page_size: int
