"""Application configuration loaded from environment variables.

All runtime configuration flows through :class:`Settings` so the app, the
Celery workers and the test suite share one source of truth.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings sourced from the environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "bulk-certificate-generator"
    app_env: str = "development"
    log_level: str = "INFO"

    # Validation
    max_batch_size: int = 1000

    # Database
    database_url: str = "postgresql+psycopg://certs:certs@localhost:5432/certs"

    # Celery / Redis
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Storage
    storage_backend: str = "local"
    storage_local_dir: str = "storage"

    # Reliability tuning
    recipient_lock_timeout_seconds: int = 300
    max_retries: int = 3
    retry_backoff_base_seconds: int = 5


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance (one per process)."""
    return Settings()
