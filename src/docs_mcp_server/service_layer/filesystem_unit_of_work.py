"""Unit of Work for Filesystem."""

from abc import ABC, abstractmethod
import contextlib
import logging
from pathlib import Path
import shutil
from typing import ClassVar
import uuid

from docs_mcp_server.adapters.filesystem_repository import (
    AbstractRepository,
    DualModeFileSystemRepository,
    FakeRepository,
)
from docs_mcp_server.domain.model import Document
from docs_mcp_server.utils.path_builder import PathBuilder
from docs_mcp_server.utils.url_translator import UrlTranslator


logger = logging.getLogger(__name__)

# Staging directory prefix - each UoW instance gets a unique subdirectory
STAGING_DIR_PREFIX = ".staging_"


def cleanup_orphaned_staging_dirs(base_dir: Path, max_age_hours: float = 1.0) -> int:
    """Clean up orphaned staging directories from crashed processes.

    Staging directories older than max_age_hours are considered orphaned and removed.
    This should be called at application startup before creating new UoW instances.

    Args:
        base_dir: Base directory containing staging subdirectories
        max_age_hours: Maximum age in hours before a staging dir is considered orphaned

    Returns:
        Number of staging directories cleaned up
    """
    import time

    cleaned_count = 0
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600

    try:
        for entry in base_dir.iterdir():
            if not entry.is_dir():
                continue

            # Match both legacy .staging and new .staging_<uuid> pattern
            if entry.name == ".staging" or entry.name.startswith(STAGING_DIR_PREFIX):
                try:
                    # Check directory age based on modification time
                    dir_mtime = entry.stat().st_mtime
                    age_seconds = current_time - dir_mtime

                    if age_seconds > max_age_seconds:
                        shutil.rmtree(entry)
                        cleaned_count += 1
                        logger.info(f"Cleaned up orphaned staging directory: {entry}")
                except OSError as e:
                    logger.warning(f"Failed to clean up staging directory {entry}: {e}")
    except OSError as e:
        logger.warning(f"Failed to iterate base directory {base_dir}: {e}")

    return cleaned_count


class AbstractUnitOfWork(ABC):
    """Abstract Unit of Work."""

    documents: AbstractRepository

    async def __aenter__(self):
        """Enter transaction context."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit transaction context - rollback unless explicitly committed."""
        # Only rollback if we haven't committed yet
        if not getattr(self, "_committed", False):
            await self.rollback()

    @abstractmethod
    async def commit(self):
        """Commit the transaction."""
        raise NotImplementedError

    @abstractmethod
    async def rollback(self):
        """Rollback the transaction."""
        raise NotImplementedError


class FileSystemUnitOfWork(AbstractUnitOfWork):
    """Unit of Work for filesystem operations.

    Uses a dual-repository pattern:
    - Reads from base_dir (permanent storage)
    - Writes to staging_dir (transactional staging area)

    IMPORTANT: Each UoW instance gets a unique staging directory (UUID-based) to prevent
    race conditions when multiple async tasks create UoW instances concurrently.
    Without this isolation, one task's __aenter__ would delete another task's staged files.
    """

    def __init__(
        self,
        base_dir: Path,
        url_translator: UrlTranslator,
        *,
        path_builder: PathBuilder | None = None,
        allow_missing_metadata_for_base: bool = False,
    ):
        resolved_base = base_dir.expanduser().resolve(strict=False)
        self.base_dir = resolved_base
        self.base_url_translator = url_translator  # Keep reference to base translator
        # Use unique staging subdirectory per UoW instance to avoid race conditions
        # Each async task gets its own staging area that won't be deleted by other tasks
        self._staging_id = uuid.uuid4().hex[:8]
        self.staging_dir = self.base_dir / f"{STAGING_DIR_PREFIX}{self._staging_id}"
        self.path_builder = path_builder
        self._committed = False

        # Ensure base directory exists (staging created in __aenter__)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Create a dual-mode repository that reads from base_dir but writes to staging_dir
        self.documents = DualModeFileSystemRepository(
            base_dir=self.base_dir,
            staging_dir=self.staging_dir,
            base_url_translator=url_translator,
            path_builder=path_builder,
            allow_missing_metadata_for_base=allow_missing_metadata_for_base,
        )

    async def __aenter__(self):
        # Create fresh staging directory for this UoW instance
        # No need to clean up - each instance has a unique UUID-based directory
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self._committed = False  # Reset committed flag
        return self

    async def commit(self):
        """Commit changes by moving from staging to main directory."""
        self._merge_staging_into_base()
        # Clean up empty staging directory
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)
        self._committed = True  # Mark as committed

    async def rollback(self):
        """Rollback by deleting the staging directory."""
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)
        self._committed = False  # Reset committed flag

    def _merge_staging_into_base(self) -> None:
        """Copy staged files into base directory without deleting siblings."""

        if not self.staging_dir.exists():
            return

        # Move each staged file into its destination, creating parents as needed
        staged_paths = sorted(self.staging_dir.rglob("*"))
        for path in staged_paths:
            if not path.is_file():
                continue

            relative_path = path.relative_to(self.staging_dir)
            destination = self.base_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)

            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()

            shutil.move(str(path), str(destination))

        # Remove any empty directories left behind in staging
        for directory in sorted(self.staging_dir.rglob("*"), reverse=True):
            if directory.is_dir():
                with contextlib.suppress(OSError):
                    directory.rmdir()


class FakeUnitOfWork(AbstractUnitOfWork):
    """In-memory Unit of Work for testing."""

    _shared_store: ClassVar[dict[str, Document]] = {}

    def __init__(self):
        self.documents = FakeRepository()
        self.committed = False

    @classmethod
    def clear_shared_store(cls):
        """Clear the shared store (for test isolation)."""
        cls._shared_store.clear()

    async def __aenter__(self):
        for doc in self._shared_store.values():
            await self.documents.add(doc)
        return self

    async def commit(self):
        self.committed = True
        docs = await self.documents.list(limit=100000)
        store = type(self)._shared_store
        store.clear()
        for doc in docs:
            store[str(doc.url)] = doc

    async def rollback(self):
        # FakeRepository has a clear() method for testing
        if hasattr(self.documents, "clear"):
            self.documents.clear()  # type: ignore[attr-defined]
        self.committed = False
