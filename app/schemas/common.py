"""Shared response schemas."""
from __future__ import annotations

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Consistent error envelope returned for 4xx/5xx responses."""

    detail: str


class HealthResponse(BaseModel):
    status: str
    database: str
    broker: str
