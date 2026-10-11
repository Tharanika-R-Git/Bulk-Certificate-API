"""Storage abstraction.

A narrow interface keeps PDF persistence decoupled from the filesystem so an
object-storage backend (S3, GCS, ...) can be added later without touching
callers. Storage keys are always server-generated from UUIDs; we additionally
reject any key that could escape the storage root.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

# Keys look like: jobs/<uuid>/certificates/<uuid>.pdf
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.\-]*$")


class StorageError(Exception):
    """Base error for storage backends."""


class ObjectNotFound(StorageError):
    """Raised when a requested key does not exist."""


def validate_key(key: str) -> str:
    """Reject empty, absolute, traversal or otherwise unsafe keys."""
    if not key or not _SAFE_KEY.match(key):
        raise StorageError(f"invalid storage key: {key!r}")
    if ".." in key.split("/") or key.startswith("/"):
        raise StorageError(f"unsafe storage key: {key!r}")
    return key


class Storage(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes) -> str: ...

    @abstractmethod
    def load(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def resolve_path(self, key: str) -> Path | None:
        """Return a filesystem path if the backend is file based, else None."""


class LocalStorage(Storage):
    """Stores objects on the local filesystem under ``base_dir``."""

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir).resolve()
        self._base.mkdir(parents=True, exist_ok=True)

    def _full_path(self, key: str) -> Path:
        validate_key(key)
        # Resolve and confirm the final path stays within the storage root.
        target = (self._base / key).resolve()
        if not target.is_relative_to(self._base):
            raise StorageError(f"key escapes storage root: {key!r}")
        return target

    def save(self, key: str, data: bytes) -> str:
        target = self._full_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file then atomically replace to avoid partial reads.
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        return key

    def load(self, key: str) -> bytes:
        target = self._full_path(key)
        if not target.is_file():
            raise ObjectNotFound(key)
        return target.read_bytes()

    def exists(self, key: str) -> bool:
        try:
            return self._full_path(key).is_file()
        except StorageError:
            return False

    def resolve_path(self, key: str) -> Path | None:
        target = self._full_path(key)
        return target if target.is_file() else None


def build_storage() -> Storage:
    """Factory that returns the configured storage backend."""
    from app.core.config import get_settings

    settings = get_settings()
    if settings.storage_backend == "local":
        return LocalStorage(settings.storage_local_dir)
    raise StorageError(f"unknown storage backend: {settings.storage_backend}")


def certificate_key(job_id: object, recipient_id: object) -> str:
    """Build the canonical, collision-free storage key for a certificate."""
    return f"jobs/{job_id}/certificates/{recipient_id}.pdf"
