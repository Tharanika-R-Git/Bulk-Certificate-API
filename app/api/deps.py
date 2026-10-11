"""Shared API dependencies and URL helpers."""
from __future__ import annotations

import uuid

from app.services.storage import Storage, build_storage

API_V1 = "/api/v1"


def get_storage() -> Storage:
    return build_storage()


def job_status_url(job_id: uuid.UUID) -> str:
    return f"{API_V1}/certificate-jobs/{job_id}"


def certificate_download_url(job_id: uuid.UUID, recipient_id: uuid.UUID) -> str:
    return f"{API_V1}/certificate-jobs/{job_id}/certificates/{recipient_id}"


def progress_percentage(total: int, processed: int) -> float:
    if total <= 0:
        return 0.0
    return round(processed / total * 100, 2)
