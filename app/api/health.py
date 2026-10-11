"""Health / readiness endpoint."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.database import get_sessionmaker
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


def _check_database() -> bool:
    try:
        session = get_sessionmaker()()
        try:
            session.execute(text("SELECT 1"))
        finally:
            session.close()
        return True
    except Exception as exc:  # pragma: no cover - exercised only when DB down
        logger.warning("database health check failed", extra={"extra": {"detail": repr(exc)}})
        return False


def _check_broker() -> bool:
    settings = get_settings()
    try:
        import redis  # local import; keeps health check optional

        client = redis.Redis.from_url(settings.celery_broker_url, socket_connect_timeout=1)
        return bool(client.ping())
    except Exception as exc:  # pragma: no cover - exercised only when broker down
        logger.warning("broker health check failed", extra={"extra": {"detail": repr(exc)}})
        return False


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness (always 'ok' if we respond) plus DB and broker readiness."""
    db_ok = _check_database()
    broker_ok = _check_broker()
    return HealthResponse(
        status="ok",
        database="up" if db_ok else "down",
        broker="up" if broker_ok else "down",
    )
