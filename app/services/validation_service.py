"""Recipient-level validation.

Job-level validation (event name, issuer, issue date present; batch non-empty
and within ``MAX_BATCH_SIZE``) is enforced by Pydantic / the endpoint and
rejects the whole request with HTTP 422.

Recipient-level validation never rejects the request: each invalid recipient is
recorded as a FAILED result with a safe, human-readable message while valid
recipients proceed. The two concerns are deliberately separated.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.schemas.jobs import RecipientInput

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class ValidatedRecipient:
    index: int
    name: str
    email: str
    certificate_number: str


@dataclass
class RejectedRecipientData:
    index: int
    certificate_number: str
    error: str


@dataclass
class ValidationResult:
    valid: list[ValidatedRecipient] = field(default_factory=list)
    rejected: list[RejectedRecipientData] = field(default_factory=list)


def _recipient_errors(r: RecipientInput) -> list[str]:
    errors: list[str] = []
    if not r.name.strip():
        errors.append("name is required")
    if not r.email.strip():
        errors.append("email is required")
    elif not _EMAIL_RE.match(r.email.strip()):
        errors.append("email format is invalid")
    if not r.certificate_number.strip():
        errors.append("certificate number is required")
    return errors


def validate_recipients(recipients: list[RecipientInput]) -> ValidationResult:
    """Split recipients into valid and rejected buckets.

    Duplicate certificate numbers within the batch cause *every* recipient
    sharing that number to be rejected, because the correct owner is ambiguous
    and the per-job uniqueness constraint would otherwise block them anyway.
    """
    result = ValidationResult()

    # Count non-empty certificate numbers to detect in-batch duplicates.
    counts = Counter(
        r.certificate_number.strip()
        for r in recipients
        if r.certificate_number.strip()
    )
    duplicates = {num for num, n in counts.items() if n > 1}

    for i, r in enumerate(recipients):
        errors = _recipient_errors(r)
        cert = r.certificate_number.strip()
        if cert and cert in duplicates:
            errors.append("duplicate certificate number within batch")

        if errors:
            result.rejected.append(
                RejectedRecipientData(index=i, certificate_number=cert, error="; ".join(errors))
            )
        else:
            result.valid.append(
                ValidatedRecipient(
                    index=i,
                    name=r.name.strip(),
                    email=r.email.strip(),
                    certificate_number=cert,
                )
            )
    return result
