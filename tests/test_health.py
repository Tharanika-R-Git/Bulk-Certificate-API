"""Health endpoint test."""
from __future__ import annotations


def test_health_reports_database_up(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"
    # Broker is not running in the unit test environment; the field still exists.
    assert body["broker"] in {"up", "down"}
