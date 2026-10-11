"""API tests for job creation and status."""
from __future__ import annotations

import uuid

from app.db.enums import JobStatus


def test_create_job_returns_202(client, sample_payload):
    resp = client.post("/api/v1/certificate-jobs", json=sample_payload)
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] == 2
    assert body["rejected"] == 0
    assert body["total_recipients"] == 2
    assert body["status"] == JobStatus.QUEUED.value
    assert body["status_url"].endswith(body["job_id"])


def test_create_job_rejects_missing_event_name(client, sample_payload):
    sample_payload.pop("event_name")
    resp = client.post("/api/v1/certificate-jobs", json=sample_payload)
    assert resp.status_code == 422


def test_create_job_rejects_empty_recipients(client, sample_payload):
    sample_payload["recipients"] = []
    resp = client.post("/api/v1/certificate-jobs", json=sample_payload)
    assert resp.status_code == 422


def test_create_job_enforces_batch_size(client, sample_payload):
    # conftest sets MAX_BATCH_SIZE=10
    sample_payload["recipients"] = [
        {"name": f"User {i}", "email": f"u{i}@example.com", "certificate_number": f"C{i}"}
        for i in range(11)
    ]
    resp = client.post("/api/v1/certificate-jobs", json=sample_payload)
    assert resp.status_code == 422
    assert "batch size" in resp.json()["detail"]


def test_partially_invalid_batch_is_accepted(client, sample_payload):
    sample_payload["recipients"] = [
        {"name": "Valid", "email": "valid@example.com", "certificate_number": "OK-1"},
        {"name": "", "email": "bad", "certificate_number": ""},  # invalid
    ]
    resp = client.post("/api/v1/certificate-jobs", json=sample_payload)
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] == 1
    assert body["rejected"] == 1


def test_duplicate_certificate_numbers_rejected(client, sample_payload):
    sample_payload["recipients"] = [
        {"name": "A", "email": "a@example.com", "certificate_number": "DUP"},
        {"name": "B", "email": "b@example.com", "certificate_number": "DUP"},
    ]
    resp = client.post("/api/v1/certificate-jobs", json=sample_payload)
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] == 0
    assert body["rejected"] == 2


def test_get_job_status(client, sample_payload):
    job_id = client.post("/api/v1/certificate-jobs", json=sample_payload).json()["job_id"]
    resp = client.get(f"/api/v1/certificate-jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["progress_percentage"] == 0.0
    assert body["success_count"] == 0


def test_get_unknown_job_returns_404(client):
    resp = client.get(f"/api/v1/certificate-jobs/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_all_invalid_batch_finalizes_as_failed(client, sample_payload):
    sample_payload["recipients"] = [
        {"name": "", "email": "bad", "certificate_number": ""},
    ]
    job_id = client.post("/api/v1/certificate-jobs", json=sample_payload).json()["job_id"]
    body = client.get(f"/api/v1/certificate-jobs/{job_id}").json()
    assert body["status"] == JobStatus.FAILED.value
    assert body["progress_percentage"] == 100.0
