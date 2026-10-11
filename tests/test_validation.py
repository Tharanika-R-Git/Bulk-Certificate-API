"""Unit tests for recipient-level validation."""
from __future__ import annotations

from app.schemas.jobs import RecipientInput
from app.services.validation_service import validate_recipients


def _mk(name="A", email="a@example.com", cert="C1") -> RecipientInput:
    return RecipientInput(name=name, email=email, certificate_number=cert)


def test_all_valid():
    result = validate_recipients([_mk(cert="C1"), _mk(cert="C2")])
    assert len(result.valid) == 2
    assert result.rejected == []


def test_missing_name_rejected():
    result = validate_recipients([_mk(name="", cert="C1")])
    assert len(result.valid) == 0
    assert "name is required" in result.rejected[0].error


def test_invalid_email_rejected():
    result = validate_recipients([_mk(email="not-an-email", cert="C1")])
    assert "email format is invalid" in result.rejected[0].error


def test_missing_certificate_number_rejected():
    result = validate_recipients([_mk(cert="")])
    assert "certificate number is required" in result.rejected[0].error


def test_duplicate_certificate_numbers_all_rejected():
    result = validate_recipients([_mk(cert="DUP"), _mk(cert="DUP"), _mk(cert="UNIQUE")])
    rejected_certs = {r.certificate_number for r in result.rejected}
    assert rejected_certs == {"DUP"}
    assert len(result.rejected) == 2
    assert [v.certificate_number for v in result.valid] == ["UNIQUE"]


def test_multiple_errors_combined():
    result = validate_recipients([_mk(name="", email="bad", cert="")])
    msg = result.rejected[0].error
    assert "name is required" in msg
    assert "email format is invalid" in msg
    assert "certificate number is required" in msg
