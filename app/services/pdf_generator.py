"""Certificate PDF rendering with ReportLab.

A single fixed, professional landscape template. All displayed values are
sanitized (control characters stripped, length-capped) before drawing so a
malicious or oversized recipient name cannot corrupt the document or layout.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

_PAGE = landscape(A4)
_WIDTH, _HEIGHT = _PAGE

_INK = HexColor("#1a2b4a")
_ACCENT = HexColor("#b08d57")  # muted gold
_MUTED = HexColor("#5a6475")


def _sanitize(value: str, *, max_len: int = 120) -> str:
    """Strip control characters and cap length for safe rendering."""
    cleaned = "".join(ch for ch in str(value) if ch == " " or ch.isprintable())
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


@dataclass(frozen=True)
class CertificateData:
    event_name: str
    recipient_name: str
    certificate_number: str
    issue_date: date
    issuer_name: str


class CertificateGenerator:
    """Renders :class:`CertificateData` into PDF bytes."""

    def render(self, data: CertificateData) -> bytes:
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=_PAGE)
        c.setTitle("Certificate")
        c.setAuthor(_sanitize(data.issuer_name))

        self._draw_borders(c)
        self._draw_body(c, data)

        c.showPage()
        c.save()
        return buffer.getvalue()

    def _draw_borders(self, c: canvas.Canvas) -> None:
        c.setStrokeColor(_INK)
        c.setLineWidth(3)
        c.rect(12 * mm, 12 * mm, _WIDTH - 24 * mm, _HEIGHT - 24 * mm)
        c.setStrokeColor(_ACCENT)
        c.setLineWidth(1)
        c.rect(16 * mm, 16 * mm, _WIDTH - 32 * mm, _HEIGHT - 32 * mm)

    def _draw_body(self, c: canvas.Canvas, data: CertificateData) -> None:
        center = _WIDTH / 2

        c.setFillColor(_INK)
        c.setFont("Helvetica-Bold", 34)
        c.drawCentredString(center, _HEIGHT - 55 * mm, "Certificate of Completion")

        c.setFillColor(_MUTED)
        c.setFont("Helvetica", 14)
        c.drawCentredString(center, _HEIGHT - 70 * mm, "This certificate is proudly presented to")

        c.setFillColor(_INK)
        c.setFont("Helvetica-Bold", 30)
        c.drawCentredString(center, _HEIGHT - 92 * mm, _sanitize(data.recipient_name))

        # Underline beneath the recipient name.
        c.setStrokeColor(_ACCENT)
        c.setLineWidth(1)
        c.line(center - 90 * mm, _HEIGHT - 96 * mm, center + 90 * mm, _HEIGHT - 96 * mm)

        c.setFillColor(_MUTED)
        c.setFont("Helvetica", 14)
        c.drawCentredString(center, _HEIGHT - 110 * mm, "for successfully completing")
        c.setFillColor(_INK)
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(center, _HEIGHT - 120 * mm, _sanitize(data.event_name))

        # Footer row: issuer (left), issue date (right), certificate no. (centre).
        baseline = 30 * mm
        c.setFillColor(_INK)
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(90 * mm, baseline + 6 * mm, _sanitize(data.issuer_name, max_len=60))
        c.drawCentredString(_WIDTH - 90 * mm, baseline + 6 * mm, data.issue_date.isoformat())

        c.setFillColor(_MUTED)
        c.setFont("Helvetica", 10)
        c.drawCentredString(90 * mm, baseline, "Issued by")
        c.drawCentredString(_WIDTH - 90 * mm, baseline, "Date of issue")

        c.setFillColor(_MUTED)
        c.setFont("Helvetica", 10)
        c.drawCentredString(
            center,
            18 * mm,
            f"Certificate No: {_sanitize(data.certificate_number, max_len=80)}",
        )
