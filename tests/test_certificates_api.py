"""API tests for certificate download."""
from __future__ import annotations

import uuid

from tests.helpers import drive_processing


def _create_and_process(client, payload):
    job_id = client.post("/api/v1/certificate-jobs", json=payload).json()["job_id"]
    drive_processing(uuid.UUID(job_id))
    recipients = client.get(f"/api/v1/certificate-jobs/{job_id}/recipients").json()["items"]
    return job_id, recipients


def test_download_successful_certificate(client, sample_payload):
    job_id, recipients = _create_and_process(client, sample_payload)
    rid = recipients[0]["recipient_id"]
    resp = client.get(f"/api/v1/certificate-jobs/{job_id}/certificates/{rid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    assert "attachment" in resp.headers["content-disposition"]


def test_download_unknown_recipient_404(client, sample_payload):
    job_id = client.post("/api/v1/certificate-jobs", json=sample_payload).json()["job_id"]
    resp = client.get(f"/api/v1/certificate-jobs/{job_id}/certificates/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_download_unsuccessful_recipient_409(client, sample_payload):
    sample_payload["recipients"] = [{"name": "", "email": "bad", "certificate_number": ""}]
    job_id = client.post("/api/v1/certificate-jobs", json=sample_payload).json()["job_id"]
    rid = client.get(f"/api/v1/certificate-jobs/{job_id}/recipients").json()["items"][0]["recipient_id"]
    resp = client.get(f"/api/v1/certificate-jobs/{job_id}/certificates/{rid}")
    assert resp.status_code == 409


def test_download_recipient_from_different_job_404(client, sample_payload):
    # Job A with a successful recipient.
    job_a, recipients_a = _create_and_process(client, sample_payload)
    rid_a = recipients_a[0]["recipient_id"]

    # Job B unrelated.
    other = dict(sample_payload)
    other["recipients"] = [{"name": "Z", "email": "z@example.com", "certificate_number": "ZZZ"}]
    job_b = client.post("/api/v1/certificate-jobs", json=other).json()["job_id"]

    # Recipient of A requested under B's id must not resolve.
    resp = client.get(f"/api/v1/certificate-jobs/{job_b}/certificates/{rid_a}")
    assert resp.status_code == 404
