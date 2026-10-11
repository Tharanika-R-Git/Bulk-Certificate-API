"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import certificates, health, jobs, recipients
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("application started", extra={"extra": {"env": settings.app_env}})
    yield
    logger.info("application stopping")


app = FastAPI(
    title="Bulk Certificate Generator",
    version="1.0.0",
    description=(
        "Accepts bulk certificate-generation jobs, validates recipients, "
        "generates PDFs asynchronously via Celery, and exposes job progress "
        "and certificate downloads."
    ),
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(recipients.router)
app.include_router(certificates.router)
