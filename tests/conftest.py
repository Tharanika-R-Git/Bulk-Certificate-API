"""Pytest fixtures.

The suite runs fully offline: an isolated SQLite database and a temp storage
directory stand in for PostgreSQL and the filesystem, and no Redis/Celery
process is required. Environment variables are set *before* importing the app
so the cached settings/engine pick them up.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="certtest_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["STORAGE_LOCAL_DIR"] = (_TMP / "storage").as_posix()
os.environ["CELERY_BROKER_URL"] = "memory://"
os.environ["CELERY_RESULT_BACKEND"] = "cache+memory://"
os.environ["MAX_BATCH_SIZE"] = "10"
os.environ["MAX_RETRIES"] = "2"
os.environ["RECIPIENT_LOCK_TIMEOUT_SECONDS"] = "300"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.db.database import get_engine, get_sessionmaker  # noqa: E402
from app.db.models import Base, CertificateJob, CertificateRecipient, OutboxEntry  # noqa: E402
from app.main import app  # noqa: E402
from app.services.pdf_generator import CertificateGenerator  # noqa: E402
from app.services.storage import build_storage  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> None:
    Base.metadata.create_all(get_engine())


@pytest.fixture(autouse=True)
def _clean_tables():
    """Isolate tests by clearing all rows after each one."""
    yield
    session = get_sessionmaker()()
    try:
        session.execute(delete(OutboxEntry))
        session.execute(delete(CertificateRecipient))
        session.execute(delete(CertificateJob))
        session.commit()
    finally:
        session.close()


@pytest.fixture
def db():
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def storage():
    return build_storage()


@pytest.fixture
def generator() -> CertificateGenerator:
    return CertificateGenerator()


@pytest.fixture
def sample_payload() -> dict:
    return {
        "event_name": "Advanced Python Workshop",
        "issuer_name": "Acme Academy",
        "issue_date": "2026-10-11",
        "recipients": [
            {"name": "Ada Lovelace", "email": "ada@example.com", "certificate_number": "CERT-001"},
            {"name": "Alan Turing", "email": "alan@example.com", "certificate_number": "CERT-002"},
        ],
    }
