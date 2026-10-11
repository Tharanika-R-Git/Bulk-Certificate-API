"""Database engine and session management (SQLAlchemy 2.x).

The engine is created lazily from :func:`get_settings` so the test suite can
point ``DATABASE_URL`` at an isolated SQLite database before anything connects.
"""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    connect_args: dict[str, object] = {}
    url = settings.database_url
    if url.startswith("sqlite"):
        # Needed so a SQLite connection can be shared across threads in tests.
        connect_args["check_same_thread"] = False
    return create_engine(url, pool_pre_ping=True, future=True, connect_args=connect_args)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a request-scoped session."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
