"""Filesystem-based repository implementation."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import anyio

from docs_mcp_server.domain.model import Document
from docs_mcp_server.utils.front_matter import parse_front_matter, serialize_front_matter
from docs_mcp_server.utils.path_builder import PathBuilder
from docs_mcp_server.utils.url_translator import UrlTranslator


logger = logging.getLogger(__name__)

# Constants
META_FILE_EXTENSION = ".meta.json"
FILE_SCHEME = "file://"


def _document_key_for_canonical_url(canonical_url: str) -> str:
    """Hash canonical URL into document key."""
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()


class AbstractRepository(ABC):
    """Abstract repository for Document aggregate."""

    @abstractmethod
    async def add(self, document: Document) -> None:
        """Add a document to the repository."""
        raise NotImplementedError

    @abstractmethod
    async def get(self, url: str) -> Document | None:
        """Get a document by URL (identity)."""
        raise NotImplementedError

    @abstractmethod
    async def list(self, limit: int = 100) -> list[Document]:
        """List documents (for sync operations)."""
        raise NotImplementedError

    @abstractmethod
    async def count(self) -> int:
        """Count total documents."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, url: str) -> bool:
        """Delete a document by URL.

        Args:
            url: Document URL to delete

        Returns:
            True if document was deleted, False if not found
        """
        raise NotImplementedError

    @abstractmethod
    async def delete_by_path_builder(self, url: str) -> bool:
        """Delete document using PathBuilder structure (nested folders).

        Args:
            url: Document URL to delete

        Returns:
            True if document was deleted, False if not found
        """
        raise NotImplementedError

    @abstractmethod
    async def delete_by_url_translator(self, url: str) -> bool:
        """Delete document using URLTranslator structure (SHA-256 hashed paths).

        Args:
            url: Document URL to delete

        Returns:
            True if document was deleted, False if not found
        """
        raise NotImplementedError


class FileSystemRepository(AbstractRepository):
    """Repository implementation using the filesystem.

    Stores documents as files on disk.
    - Content is stored in a markdown file.
    - Metadata is stored in a corresponding .meta.json file.
    """

    def __init__(
        self,
        base_dir: Path,
        url_translator: UrlTranslator,
        path_builder: PathBuilder | None = None,
        *,
        allow_missing_metadata: bool = False,
    ):
        """Initialize with a base directory for storage.

        Args:
            base_dir: Base directory for document storage
            url_translator: URL to filesystem path translator
            path_builder: Optional PathBuilder for nested folder structure
        """
        expanded_base = base_dir.expanduser()
        self.base_dir = expanded_base.resolve(strict=False)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.url_translator = url_translator
        self.path_builder = path_builder
        # PathBuilder is required for document keys; use provided builder or lazily
        # instantiate a lightweight one when needed for metadata enrichment.
        self._metadata_path_builder = path_builder or PathBuilder()
        self.allow_missing_metadata = allow_missing_metadata

    async def add(self, document: Document) -> None:
        """Add or update a document on the filesystem."""
        url_value = str(document.url.value)

        if self.path_builder:
            content_path = self.path_builder.build_markdown_path(url_value, relative_to=self.base_dir)
            meta_path = self.path_builder.build_metadata_path(content_path, relative_to=self.base_dir)
        else:
            content_path = self.url_translator.get_internal_path_from_public_url(url_value)
            meta_path = content_path.with_suffix(META_FILE_EXTENSION)

        try:
            # Ensure parent directory exists
            content_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.parent.mkdir(parents=True, exist_ok=True)

            # Prepare metadata fields prior to serialization
            relative_markdown_path = self._relative_to_base(content_path)
            document.metadata.markdown_rel_path = relative_markdown_path

            canonical_url = self._metadata_path_builder.canonicalize_url(url_value)
            document.metadata.document_key = _document_key_for_canonical_url(canonical_url)

            metadata_dict = self._metadata_to_serializable_dict(document)
            front_matter_payload = self._build_front_matter_payload(document, metadata_dict)

            markdown_with_front_matter = serialize_front_matter(
                front_matter_payload,
                document.content.markdown,
            )

            # Write content with YAML front matter header
            async with await anyio.open_file(content_path, "w", encoding="utf-8") as f:
                await f.write(markdown_with_front_matter)

            meta_data = {
                "url": str(document.url.value),
                "title": document.title,
                "metadata": metadata_dict,
            }
            async with await anyio.open_file(meta_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(meta_data, indent=2))

        except OSError as e:
            logger.error(f"Failed to write document {document.url.value}: {e}")

    async def get(self, url: str) -> Document | None:
        """Get a document from the filesystem."""

        content_path, meta_path = self._resolve_paths(url)
        if not content_path or not content_path.exists():
            return None

        markdown_result = await self._read_markdown_with_front_matter(content_path)
        if not markdown_result:
            return None

        front_matter_metadata, markdown = markdown_result
        meta_data = await self._load_metadata_file(meta_path) if meta_path else None

        if meta_data:
            document = self._hydrate_from_metadata(meta_data, url, markdown, front_matter_metadata)
            return document

        if not self.allow_missing_metadata or not url.startswith(FILE_SCHEME):
            return None

        return self._hydrate_from_front_matter_only(url, markdown, front_matter_metadata, content_path)

    def _derive_title_from_markdown(
        self,
        content_path: Path,
        markdown: str,
        front_matter_metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """Create a best-effort title when metadata is unavailable."""
        if front_matter_metadata:
            title = front_matter_metadata.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()

        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                candidate = stripped.lstrip("#").strip()
                if candidate:
                    return candidate

        # Fallback to filename-based title
        stem = content_path.stem.replace("-", " ").replace("_", " ")
        title = stem.strip().title()
        return title or "Untitled Document"

    async def list(self, limit: int = 100) -> list[Document]:
        """List documents from the filesystem."""
        documents = []
        for meta_file in self.base_dir.rglob(f"*{META_FILE_EXTENSION}"):
            if len(documents) >= limit:
                break
            url = json.loads(meta_file.read_text())["url"]
            doc = await self.get(url)
            if doc:
                documents.append(doc)
        return documents

    async def count(self) -> int:
        """Count total documents."""
        return sum(1 for _ in self.base_dir.rglob(f"*{META_FILE_EXTENSION}"))

    async def delete(self, url: str) -> bool:
        """Delete a document from the filesystem.

        Args:
            url: Document URL to delete

        Returns:
            True if document was deleted, False if not found
        """
        if url.startswith(FILE_SCHEME):
            content_path = Path(urlparse(url).path)
            meta_path = content_path.with_suffix(META_FILE_EXTENSION)
        else:
            if self.path_builder:
                deleted = await self.delete_by_path_builder(url)
                if deleted:
                    return True
            content_path = self.url_translator.get_internal_path_from_public_url(url)
            meta_path = content_path.with_suffix(META_FILE_EXTENSION)

        if not content_path.exists() and not meta_path.exists():
            return False

        try:
            if content_path.exists():
                content_path.unlink()

            if meta_path.exists():
                meta_path.unlink()

            return True

        except OSError as e:
            logger.error(f"Failed to delete document {url}: {e}")
            return False

    async def delete_by_path_builder(self, url: str) -> bool:
        """Delete document using PathBuilder for path resolution.

        Args:
            url: Canonical URL of document to delete

        Returns:
            True if document was deleted, False if not found
        """
        if not self.path_builder:
            logger.warning("PathBuilder not configured; falling back to URLTranslator deletion")
            return await self.delete_by_url_translator(url)

        try:
            markdown_path = self.path_builder.build_markdown_path(url, relative_to=self.base_dir)
            metadata_path = self.path_builder.build_metadata_path(markdown_path, relative_to=self.base_dir)

            deleted = False
            if markdown_path.exists():
                markdown_path.unlink()
                deleted = True

            if metadata_path.exists():
                metadata_path.unlink()
                deleted = True

            if deleted:
                # Prune empty directories
                self._prune_empty_dirs(markdown_path.parent)
                self._prune_empty_dirs(metadata_path.parent)

            return deleted
        except Exception as e:
            logger.error(f"Error deleting document {url}: {e}")
            return False

    async def delete_by_url_translator(self, url: str) -> bool:
        """Delete document using URLTranslator structure (SHA-256 hashed paths).

        Args:
            url: Document URL to delete

        Returns:
            True if document was deleted, False if not found
        """
        content_path = self.url_translator.get_internal_path_from_public_url(url)
        meta_path = content_path.with_suffix(META_FILE_EXTENSION)

        if not content_path.exists() and not meta_path.exists():
            return False

        try:
            deleted = False

            # Delete content file if exists
            if content_path.exists():
                content_path.unlink()
                deleted = True

            # Delete metadata file if exists
            if meta_path.exists():
                meta_path.unlink()
                deleted = True

            return deleted

        except OSError as e:
            logger.error(f"Failed to delete document {url} using URLTranslator: {e}")
            return False

    def _prune_empty_dirs(self, directory: Path) -> None:
        """Remove empty directories up to (but not including) repository root."""
        try:
            base_dir_resolved = self.base_dir.resolve()
            metadata_root = None
            if self.path_builder:
                metadata_root = (self.base_dir / self.path_builder.METADATA_DIR).resolve()

            current = directory.resolve()
            while current != base_dir_resolved:
                if metadata_root and current == metadata_root:
                    break

                # Stop if directory has contents or is outside base dir
                if not current.exists() or any(current.iterdir()) or base_dir_resolved not in current.parents:
                    break

                current.rmdir()
                current = current.parent
        except Exception as err:
            logger.debug("Failed to prune directory %s: %s", directory, err)

    def _relative_to_base(self, path: Path) -> str:
        """Get path relative to repository base directory."""
        try:
            return str(path.relative_to(self.base_dir))
        except ValueError:
            return str(path)

    def _resolve_paths(self, url: str) -> tuple[Path | None, Path | None]:
        """Resolve content and metadata paths for a URL.

        Supports both PathBuilder (nested) and UrlTranslator (hashed) layouts.
        """
        if url.startswith(FILE_SCHEME):
            parsed_path = urlparse(url).path
            if not parsed_path or parsed_path == ".":
                return None, None
            content_path = Path(parsed_path)
            return content_path, content_path.with_suffix(META_FILE_EXTENSION)

        candidates: list[tuple[Path, Path]] = []
        if self.path_builder:
            markdown_path = self.path_builder.build_markdown_path(url, relative_to=self.base_dir)
            metadata_path = self.path_builder.build_metadata_path(markdown_path, relative_to=self.base_dir)
            candidates.append((markdown_path, metadata_path))

        hashed_content = self.url_translator.get_internal_path_from_public_url(url)
        candidates.append((hashed_content, hashed_content.with_suffix(META_FILE_EXTENSION)))

        for content_path, meta_path in candidates:
            if content_path.exists() or meta_path.exists():
                return content_path, meta_path

        # Default to first candidate if no files exist yet
        return candidates[0] if candidates else (None, None)

    def _apply_metadata(self, document: Document, metadata_payload: Mapping[str, Any]) -> None:
        """Merge persisted metadata back onto document instance."""

        if not metadata_payload:
            return

        for key, value in metadata_payload.items():
            if not hasattr(document.metadata, key):
                continue

            if value is None:
                setattr(document.metadata, key, None)
                continue

            if key in {"indexed_at", "last_fetched_at", "next_due_at"}:
                try:
                    setattr(document.metadata, key, datetime.fromisoformat(value))
                except ValueError:
                    setattr(document.metadata, key, None)
                continue

            setattr(document.metadata, key, value)

    def _metadata_to_serializable_dict(self, document: Document) -> dict[str, Any]:
        """Convert document metadata to a JSON-serializable dict."""

        metadata_dict = asdict(document.metadata)
        for key, value in metadata_dict.items():
            if hasattr(value, "isoformat"):
                metadata_dict[key] = value.isoformat()
        return metadata_dict

    def _build_front_matter_payload(
        self,
        document: Document,
        metadata_dict: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Assemble YAML front matter content for persisted markdown."""

        payload: dict[str, Any] = {
            "url": str(document.url.value),
            "title": document.title,
        }

        last_fetched_at = metadata_dict.get("last_fetched_at")
        if isinstance(last_fetched_at, str) and last_fetched_at:
            payload["last_fetched_at"] = last_fetched_at

        return payload

    def _metadata_from_front_matter(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Build metadata payload from front matter fallback."""

        metadata: dict[str, Any] = {}
        nested = payload.get("metadata")
        if isinstance(nested, Mapping):
            metadata.update(nested)

        for key in ("document_key", "markdown_rel_path"):
            if key in payload and payload[key] is not None:
                metadata[key] = payload[key]

        last_fetched_at = payload.get("last_fetched_at")
        if isinstance(last_fetched_at, str) and last_fetched_at.strip():
            metadata["last_fetched_at"] = last_fetched_at

        return metadata

    async def _read_markdown_with_front_matter(
        self,
        content_path: Path,
    ) -> tuple[dict[str, Any], str] | None:
        """Load markdown file and separate YAML front matter."""

        try:
            async with await anyio.open_file(content_path, encoding="utf-8") as f:
                stored_markdown = await f.read()
        except OSError as e:
            logger.error(f"Failed to read markdown for path {content_path}: {e}")
            return None

        return parse_front_matter(stored_markdown)

    async def _load_metadata_file(self, meta_path: Path | None) -> dict[str, Any] | None:
        """Load metadata JSON file when available."""

        if not meta_path or not meta_path.exists():
            return None

        try:
            async with await anyio.open_file(meta_path, encoding="utf-8") as f:
                return json.loads(await f.read())
        except (OSError, json.JSONDecodeError) as err:
            logger.error(f"Failed to load metadata file {meta_path}: {err}")
            return None

    def _hydrate_from_metadata(
        self,
        meta_data: Mapping[str, Any],
        fallback_url: str,
        markdown: str,
        front_matter_metadata: Mapping[str, Any],
    ) -> Document | None:
        """Create Document from JSON metadata with front matter fallback."""

        doc_url = meta_data.get("url") or front_matter_metadata.get("url") or fallback_url
        title = meta_data.get("title") or front_matter_metadata.get("title") or "Untitled Document"

        document = Document.create(
            url=doc_url,
            title=str(title),
            markdown=markdown,
            text="",
        )

        metadata_payload = meta_data.get("metadata") or {}
        if not metadata_payload:
            metadata_payload = self._metadata_from_front_matter(front_matter_metadata)

        self._apply_metadata(document, metadata_payload)

        if front_matter_metadata.get("title") and not document.title.strip():
            document.title = str(front_matter_metadata["title"])

        return document

    def _hydrate_from_front_matter_only(
        self,
        url: str,
        markdown: str,
        front_matter_metadata: Mapping[str, Any],
        content_path: Path,
    ) -> Document | None:
        """Create Document when only markdown/front matter is available."""

        title = self._derive_title_from_markdown(content_path, markdown, front_matter_metadata)
        doc_url = front_matter_metadata.get("url", url)
        document = Document.create(url=doc_url, title=title, markdown=markdown, text="")

        document.metadata.mark_success()
        try:
            relative_path = content_path.relative_to(self.base_dir)
            document.metadata.markdown_rel_path = str(relative_path)
        except ValueError:
            document.metadata.markdown_rel_path = str(content_path)

        metadata_payload = front_matter_metadata.get("metadata")
        if not metadata_payload:
            metadata_payload = self._metadata_from_front_matter(front_matter_metadata)
        self._apply_metadata(document, metadata_payload)

        if front_matter_metadata.get("document_key"):
            document.metadata.document_key = str(front_matter_metadata["document_key"])

        return document


class FakeRepository(AbstractRepository):
    """In-memory repository for testing."""

    def __init__(self):
        self._documents: dict[str, Document] = {}

    async def add(self, document: Document) -> None:
        """Add document to in-memory store."""
        url_key = str(document.url.value)
        self._documents[url_key] = document

    async def get(self, url: str) -> Document | None:
        """Get document from in-memory store."""
        return self._documents.get(url)

    async def list(self, limit: int = 100) -> list[Document]:
        """List documents from in-memory store."""
        return list(self._documents.values())[:limit]

    async def count(self) -> int:
        """Count documents in in-memory store."""
        return len(self._documents)

    async def delete(self, url: str) -> bool:
        """Delete document from in-memory store.

        Args:
            url: Document URL to delete

        Returns:
            True if document was deleted, False if not found
        """
        if url in self._documents:
            del self._documents[url]
            return True
        return False

    async def delete_by_path_builder(self, url: str) -> bool:
        """Delete document from in-memory store (PathBuilder structure).

        Args:
            url: Document URL to delete

        Returns:
            True if document was deleted, False if not found
        """
        # For FakeRepository, both deletion methods work the same way
        return await self.delete(url)

    async def delete_by_url_translator(self, url: str) -> bool:
        """Delete document from in-memory store (URLTranslator structure).

        Args:
            url: Document URL to delete

        Returns:
            True if document was deleted, False if not found
        """
        # For FakeRepository, both deletion methods work the same way
        return await self.delete(url)

    def clear(self):
        """Clear all documents (for testing)."""
        self._documents.clear()


class DualModeFileSystemRepository(AbstractRepository):
    """Repository that reads from base_dir but writes to staging_dir.

    This implements the Unit of Work pattern properly:
    - GET operations read from base_dir (permanent storage)
    - ADD operations write to staging_dir (transactional staging area)
    - LIST/COUNT operations read from base_dir

    The staging_dir is committed to base_dir via UnitOfWork.commit().
    """

    def __init__(
        self,
        base_dir: Path,
        staging_dir: Path,
        base_url_translator: UrlTranslator,
        path_builder: PathBuilder | None = None,
        *,
        allow_missing_metadata_for_base: bool = False,
    ):
        """Initialize dual-mode repository.

        Args:
            base_dir: Directory for reading (permanent storage)
            staging_dir: Directory for writing (transactional staging)
            base_url_translator: URL translator configured for base_dir
        """
        self.base_dir = base_dir
        self.staging_dir = staging_dir
        self.base_url_translator = base_url_translator
        self.path_builder = path_builder

        # Create staging dir if it doesn't exist
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        # Create a staging URL translator for writes
        self.staging_url_translator = UrlTranslator(tenant_data_dir=staging_dir)

        # Create read-only repository for base_dir
        self.base_repo = FileSystemRepository(
            base_dir,
            base_url_translator,
            path_builder=path_builder,
            allow_missing_metadata=allow_missing_metadata_for_base,
        )

        # Create write repository for staging_dir
        self.staging_repo = FileSystemRepository(
            staging_dir,
            self.staging_url_translator,
            path_builder=path_builder,
        )

    async def add(self, document: Document) -> None:
        """Add document to staging directory."""
        await self.staging_repo.add(document)

    async def get(self, url: str) -> Document | None:
        """Get document from base directory (permanent storage)."""
        return await self.base_repo.get(url)

    async def list(self, limit: int = 100) -> list[Document]:
        """List documents from base directory."""
        return await self.base_repo.list(limit)

    async def count(self) -> int:
        """Count documents in base directory."""
        return await self.base_repo.count()

    async def delete(self, url: str) -> bool:
        """Delete document from base directory.

        Args:
            url: Document URL to delete

        Returns:
            True if document was deleted, False if not found
        """
        return await self.base_repo.delete(url)

    async def delete_by_path_builder(self, url: str) -> bool:
        """Delete document from base directory using PathBuilder structure.

        Args:
            url: Document URL to delete

        Returns:
            True if document was deleted, False if not found
        """
        return await self.base_repo.delete_by_path_builder(url)

    async def delete_by_url_translator(self, url: str) -> bool:
        """Delete document from base directory using URLTranslator structure.

        Args:
            url: Document URL to delete

        Returns:
            True if document was deleted, False if not found
        """
        return await self.base_repo.delete_by_url_translator(url)
