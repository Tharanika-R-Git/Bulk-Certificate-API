"""Tests for the ReportLab certificate generator."""
from __future__ import annotations

from datetime import date

from app.services.pdf_generator import CertificateData, CertificateGenerator


def test_render_produces_pdf_bytes():
    data = CertificateData(
        event_name="Python Workshop",
        recipient_name="Ada Lovelace",
        certificate_number="CERT-001",
        issue_date=date(2026, 10, 11),
        issuer_name="Acme Academy",
    )
    pdf = CertificateGenerator().render(data)
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 1000


def test_render_sanitizes_hostile_input():
    data = CertificateData(
        event_name="Workshop\x00\x07",
        recipient_name="X" * 500,  # overly long name
        certificate_number="CN\nINJECT",
        issue_date=date(2026, 1, 1),
        issuer_name="Issuer",
    )
    # Should not raise and should still yield a valid PDF.
    pdf = CertificateGenerator().render(data)
    assert pdf.startswith(b"%PDF")
