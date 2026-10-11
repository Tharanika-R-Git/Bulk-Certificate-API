"""API tests for recipient listing."""
from __future__ import annotations

import uuid

from tests.helpers import drive_processing


def test_list_recipients_paginated(client, sample_payload):
    job_id = client.post("/api/v1/certificate-jobs", json=sample_payload).json()["job_id"]
    drive_processing(uuid.UUID(job_id))

    resp = client.get(f"/api/v1/certificate-jobs/{job_id}/recipients?page=1&page_size=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert len(body["items"]) == 1

    item = body["items"][0]
    assert item["status"] == "SUCCESS"
    assert item["download_url"] is not None
    assert item["download_url"].endswith(item["recipient_id"])


def test_failed_recipient_has_no_download_url(client, sample_payload):
    sample_payload["recipients"] = [
        {"name": "", "email": "bad", "certificate_number": ""},
    ]
    job_id = client.post("/api/v1/certificate-jobs", json=sample_payload).json()["job_id"]
    body = client.get(f"/api/v1/certificate-jobs/{job_id}/recipients").json()
    assert body["items"][0]["status"] == "FAILED"
    assert body["items"][0]["download_url"] is None
    assert body["items"][0]["error_message"]


def test_list_recipients_unknown_job_404(client):
    resp = client.get(f"/api/v1/certificate-jobs/{uuid.uuid4()}/recipients")
    assert resp.status_code == 404
