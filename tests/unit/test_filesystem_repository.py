"""Unit tests for FileSystemRepository.

Following Cosmic Python Chapter 2: Repository Pattern
- Tests filesystem-based repository implementation
- Tests file I/O operations
- Tests metadata persistence
"""

from datetime import datetime
import hashlib
from pathlib import Path

import pytest

from docs_mcp_server.adapters.filesystem_repository import (
    DualModeFileSystemRepository,
    FakeRepository,
    FileSystemRepository,
)
from docs_mcp_server.domain.model import Document
from docs_mcp_server.utils.front_matter import DELIMITER, parse_front_matter
from docs_mcp_server.utils.path_builder import PathBuilder
from docs_mcp_server.utils.url_translator import UrlTranslator


@pytest.mark.unit
class TestFileSystemRepository:
    """Test FileSystemRepository implementation."""

    @pytest.fixture
    def repo_dir(self, tmp_path: Path) -> Path:
        """Create temporary directory for repository."""
        return tmp_path / "test_repo"

    @pytest.fixture
    def repo(self, repo_dir: Path) -> FileSystemRepository:
        """Create FileSystemRepository instance."""
        url_translator = UrlTranslator(tenant_data_dir=repo_dir)
        return FileSystemRepository(repo_dir, url_translator)

    @pytest.mark.asyncio
    async def test_add_creates_files(self, repo: FileSystemRepository, repo_dir: Path):
        """Test adding document creates markdown and metadata files."""
        doc = Document.create(
            url="https://example.com/test",
            title="Test Doc",
            markdown="# Test Content",
            text="Test text",
            excerpt="Test excerpt",
        )

        await repo.add(doc)

        # Verify files exist
        md_files = list(repo_dir.glob("*.md"))
        meta_files = list(repo_dir.glob("*.meta.json"))

        assert len(md_files) == 1
        assert len(meta_files) == 1

    @pytest.mark.asyncio
    async def test_front_matter_is_minimal(self, repo: FileSystemRepository, repo_dir: Path):
        """Front matter should only contain url, title, and optional last_fetched_at."""

        doc = Document.create(
            url="https://example.com/front-matter",
            title="Front Matter",
            markdown="# Front Matter",
            text="Front matter body",
            excerpt="",
        )
        doc.metadata.mark_success()

        await repo.add(doc)

        markdown_path = next(repo_dir.glob("*.md"))
        front_matter, markdown_body = parse_front_matter(markdown_path.read_text(encoding="utf-8"))

        assert markdown_body.startswith("# Front Matter")
        assert front_matter.get("url") == doc.url.value
        assert front_matter.get("title") == doc.title

        allowed_keys = {"url", "title", "last_fetched_at"}
        assert set(front_matter.keys()).issubset(allowed_keys)
        assert "metadata" not in front_matter

        if "last_fetched_at" in front_matter:
            datetime.fromisoformat(front_matter["last_fetched_at"])

    @pytest.mark.asyncio
    async def test_add_and_get_document(self, repo: FileSystemRepository):
        """Test adding and retrieving a document."""
        doc = Document.create(
            url="https://example.com/doc1", title="Test Doc", markdown="# Test", text="Test", excerpt=""
        )

        await repo.add(doc)
        retrieved = await repo.get("https://example.com/doc1")

        assert retrieved is not None
        assert retrieved.url.value == doc.url.value
        assert retrieved.title == doc.title
        assert retrieved.content.markdown == "# Test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_document(self, repo: FileSystemRepository):
        """Test getting non-existent document returns None."""
        result = await repo.get("https://example.com/missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_file_url_without_metadata_allowed(self, repo_dir: Path):
        """Test reading markdown directly when metadata is absent."""

        markdown_path = repo_dir / "chapter-01.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text("# Sample Chapter\n\nSome content.", encoding="utf-8")

        url_translator = UrlTranslator(tenant_data_dir=repo_dir)
        repo = FileSystemRepository(repo_dir, url_translator, allow_missing_metadata=True)

        document = await repo.get(f"file://{markdown_path}")

        assert document is not None
        assert document.title == "Sample Chapter"
        assert document.content.markdown.startswith("# Sample Chapter")
        assert document.metadata.status == "success"
        assert document.metadata.markdown_rel_path == "chapter-01.md"

    @pytest.mark.asyncio
    async def test_get_file_url_without_metadata_blocked_when_not_allowed(self, repo_dir: Path):
        """Test metadata fallback is disabled unless explicitly enabled."""

        markdown_path = repo_dir / "chapter-02.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text("# Another Chapter", encoding="utf-8")

        url_translator = UrlTranslator(tenant_data_dir=repo_dir)
        repo = FileSystemRepository(repo_dir, url_translator, allow_missing_metadata=False)

        document = await repo.get(f"file://{markdown_path}")

        assert document is None

    @pytest.mark.asyncio
    async def test_update_existing_document(self, repo: FileSystemRepository):
        """Test updating an existing document overwrites files."""
        doc = Document.create(
            url="https://example.com/doc", title="Original Title", markdown="# Original", text="Original", excerpt=""
        )
        await repo.add(doc)

        # Update document
        doc.title = "Updated Title"
        doc.update_content(markdown="# Updated", text="Updated", excerpt="Updated excerpt")
        await repo.add(doc)

        # Retrieve and verify
        retrieved = await repo.get("https://example.com/doc")
        assert retrieved is not None
        assert retrieved.title == "Updated Title"
        assert retrieved.content.markdown == "# Updated"

    @pytest.mark.asyncio
    async def test_list_documents(self, repo: FileSystemRepository):
        """Test listing all documents."""
        doc1 = Document.create(
            url="https://example.com/doc1", title="Doc 1", markdown="# Doc 1", text="Doc 1", excerpt=""
        )
        doc2 = Document.create(
            url="https://example.com/doc2", title="Doc 2", markdown="# Doc 2", text="Doc 2", excerpt=""
        )

        await repo.add(doc1)
        await repo.add(doc2)

        docs = await repo.list()
        assert len(docs) == 2
        urls = {doc.url.value for doc in docs}
        assert "https://example.com/doc1" in urls
        assert "https://example.com/doc2" in urls

    @pytest.mark.asyncio
    async def test_list_respects_limit(self, repo: FileSystemRepository):
        """Test list respects limit parameter."""
        for i in range(5):
            doc = Document.create(
                url=f"https://example.com/doc{i}", title=f"Doc {i}", markdown=f"# Doc {i}", text=f"Doc {i}", excerpt=""
            )
            await repo.add(doc)

        docs = await repo.list(limit=3)
        assert len(docs) == 3

    @pytest.mark.asyncio
    async def test_count_documents(self, repo: FileSystemRepository):
        """Test counting documents."""
        assert await repo.count() == 0

        doc1 = Document.create(
            url="https://example.com/doc1", title="Doc 1", markdown="# Doc 1", text="Doc 1", excerpt=""
        )
        await repo.add(doc1)
        assert await repo.count() == 1

        doc2 = Document.create(
            url="https://example.com/doc2", title="Doc 2", markdown="# Doc 2", text="Doc 2", excerpt=""
        )
        await repo.add(doc2)
        assert await repo.count() == 2

    @pytest.mark.asyncio
    async def test_repository_creates_base_directory(self, tmp_path: Path):
        """Test repository creates base directory if it doesn't exist."""
        repo_dir = tmp_path / "new_repo"
        assert not repo_dir.exists()

        url_translator = UrlTranslator(tenant_data_dir=repo_dir)
        _ = FileSystemRepository(repo_dir, url_translator)

        assert repo_dir.exists()
        assert repo_dir.is_dir()

    @pytest.mark.asyncio
    async def test_metadata_persistence(self, repo: FileSystemRepository):
        """Test document metadata is properly persisted and restored."""
        doc = Document.create(
            url="https://example.com/meta_test",
            title="Metadata Test",
            markdown="# Metadata",
            text="Metadata",
            excerpt="",
        )
        doc.metadata.mark_success()

        await repo.add(doc)

        # Retrieve and verify metadata
        retrieved = await repo.get("https://example.com/meta_test")
        assert retrieved is not None
        assert retrieved.title == "Metadata Test"

    @pytest.mark.asyncio
    async def test_path_builder_writes_nested_layout(self, repo_dir: Path):
        """PathBuilder-enabled repositories produce nested folders and metadata mirrors."""

        url_translator = UrlTranslator(tenant_data_dir=repo_dir)
        path_builder = PathBuilder()
        repo = FileSystemRepository(repo_dir, url_translator, path_builder=path_builder)

        doc = Document.create(
            url="https://docs.example.com/guide/getting-started/",
            title="Getting Started",
            markdown="# Welcome\n\nIntro content",
            text="Welcome intro",
            excerpt="",
        )

        await repo.add(doc)

        expected_markdown = path_builder.build_markdown_path(doc.url.value, relative_to=repo_dir)
        expected_metadata = path_builder.build_metadata_path(expected_markdown, relative_to=repo_dir)

        assert expected_markdown.exists()
        assert expected_metadata.exists()

        retrieved = await repo.get(doc.url.value)
        assert retrieved is not None
        assert retrieved.metadata.markdown_rel_path == str(expected_markdown.relative_to(repo_dir))

        canonical_url = path_builder.canonicalize_url(doc.url.value)
        expected_document_key = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
        assert retrieved.metadata.document_key == expected_document_key

    @pytest.mark.asyncio
    async def test_path_builder_handles_relative_roots(self, tmp_path: Path, monkeypatch):
        """Relative docs_root_dir inputs should still produce correct metadata mirrors."""

        monkeypatch.chdir(tmp_path)
        repo_dir = Path("relative-tenant")
        url_translator = UrlTranslator(tenant_data_dir=repo_dir)
        path_builder = PathBuilder()
        repo = FileSystemRepository(repo_dir, url_translator, path_builder=path_builder)

        doc = Document.create(
            url="https://docs.example.com/howto/initial-data/",
            title="How To",
            markdown="# How To\n\nSteps",
            text="How To",
            excerpt="",
        )

        await repo.add(doc)

        abs_root = repo_dir.resolve(strict=False)
        expected_markdown = path_builder.build_markdown_path(doc.url.value, relative_to=abs_root)
        expected_metadata = path_builder.build_metadata_path(expected_markdown, relative_to=abs_root)

        assert expected_markdown.exists()
        assert expected_metadata.exists()

        retrieved = await repo.get(doc.url.value)
        assert retrieved is not None
        assert retrieved.metadata.markdown_rel_path == str(expected_markdown.relative_to(abs_root))

    @pytest.mark.asyncio
    async def test_delete_with_path_builder_removes_nested_files(self, repo_dir: Path):
        """Deletion uses PathBuilder layout before falling back to hashed paths."""

        url_translator = UrlTranslator(tenant_data_dir=repo_dir)
        path_builder = PathBuilder()
        repo = FileSystemRepository(repo_dir, url_translator, path_builder=path_builder)

        doc = Document.create(
            url="https://docs.example.com/reference/api/v1/intro.html",
            title="API Intro",
            markdown="# API Intro",
            text="API Intro",
            excerpt="",
        )

        await repo.add(doc)

        markdown_path = path_builder.build_markdown_path(doc.url.value, relative_to=repo_dir)
        metadata_path = path_builder.build_metadata_path(markdown_path, relative_to=repo_dir)

        assert markdown_path.exists()
        assert metadata_path.exists()

        deleted = await repo.delete(doc.url.value)
        assert deleted is True
        assert not markdown_path.exists()
        assert not metadata_path.exists()

    @pytest.mark.asyncio
    async def test_handles_io_errors_gracefully(self, repo: FileSystemRepository, repo_dir: Path):
        """Test repository handles I/O errors gracefully."""
        doc = Document.create(url="https://example.com/test", title="Test", markdown="# Test", text="Test", excerpt="")

        # Create document first
        await repo.add(doc)

        # Make directory read-only to cause write errors
        repo_dir.chmod(0o444)

        try:
            # This should not raise an exception (errors logged internally)
            await repo.add(doc)
        finally:
            # Restore permissions
            repo_dir.chmod(0o755)

    @pytest.mark.asyncio
    async def test_front_matter_only_sets_document_metadata(self, repo_dir: Path):
        """Front matter fallback should populate metadata fields when JSON is missing."""

        markdown_path = repo_dir / "chapter" / "front-matter.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            (
                f"{DELIMITER}\n"
                "url: https://example.com/front\n"
                "document_key: front_key\n"
                "markdown_rel_path: docs/front.md\n"
                "last_fetched_at: '2024-01-01T00:00:00'\n"
                f"{DELIMITER}\n"
                "Body without headings\n"
            ),
            encoding="utf-8",
        )

        repo = FileSystemRepository(repo_dir, UrlTranslator(tenant_data_dir=repo_dir), allow_missing_metadata=True)

        document = await repo.get(f"file://{markdown_path}")

        assert document is not None
        assert document.metadata.document_key == "front_key"
        assert document.metadata.markdown_rel_path == "docs/front.md"
        assert document.metadata.last_fetched_at == datetime.fromisoformat("2024-01-01T00:00:00")

    @pytest.mark.asyncio
    async def test_title_falls_back_to_filename_without_headings(self, repo_dir: Path):
        """When no headings or front matter title exist, filename drives the title."""

        markdown_path = repo_dir / "notes" / "untitled-note.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text("Just body text without headings", encoding="utf-8")

        repo = FileSystemRepository(repo_dir, UrlTranslator(tenant_data_dir=repo_dir), allow_missing_metadata=True)
        document = await repo.get(f"file://{markdown_path}")

        assert document is not None
        assert document.title == "Untitled Note"

    def test_prune_empty_dirs_stops_at_metadata_root(self, repo_dir: Path):
        """_prune_empty_dirs should not delete the metadata mirror root."""

        path_builder = PathBuilder()
        repo = FileSystemRepository(repo_dir, UrlTranslator(tenant_data_dir=repo_dir), path_builder=path_builder)

        metadata_root = repo_dir / PathBuilder.METADATA_DIR / "docs.example.com"
        deepest = metadata_root / "section" / "topic"
        deepest.mkdir(parents=True, exist_ok=True)

        repo._prune_empty_dirs(deepest)

        assert not deepest.exists()
        assert (repo_dir / PathBuilder.METADATA_DIR).exists()

    def test_resolve_paths_handles_invalid_file_url(self, repo: FileSystemRepository):
        """file:// URLs without a path should return (None, None)."""

        content_path, meta_path = repo._resolve_paths("file://.")
        assert content_path is None
        assert meta_path is None

    @pytest.mark.asyncio
    async def test_load_metadata_file_returns_none_on_corruption(self, repo: FileSystemRepository, repo_dir: Path):
        """Corrupt metadata files should be ignored rather than raising."""

        meta_path = repo_dir / "corrupt.meta.json"
        meta_path.write_text("{not-json", encoding="utf-8")

        result = await repo._load_metadata_file(meta_path)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_none_when_metadata_corrupt_and_no_fallback(self, repo: FileSystemRepository):
        """If JSON metadata is unreadable and fallback disabled, get() returns None."""

        doc = Document.create(
            url="https://example.com/bad-meta",
            title="Bad Meta",
            markdown="# Heading",
            text="",
            excerpt="",
        )
        await repo.add(doc)

        _content_path, meta_path = repo._resolve_paths(doc.url.value)
        assert meta_path is not None
        meta_path.write_text("{oops", encoding="utf-8")

        result = await repo.get(doc.url.value)
        assert result is None

    @pytest.mark.asyncio
    async def test_front_matter_metadata_handles_external_paths(self, tmp_path: Path):
        """Front matter metadata should skip relative paths outside the repo base."""

        repo_dir = tmp_path / "tenant"
        repo_dir.mkdir(parents=True, exist_ok=True)
        external_dir = tmp_path / "external"
        external_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = external_dir / "external.md"
        markdown_path.write_text(
            (
                f"{DELIMITER}\n"
                "url: https://example.com/external\n"
                "title: External Doc\n"
                "metadata:\n"
                "  document_key: external-key\n"
                "  indexed_at: '2024-02-03T01:02:03'\n"
                f"{DELIMITER}\n"
                "Body outside repo\n"
            ),
            encoding="utf-8",
        )

        repo = FileSystemRepository(repo_dir, UrlTranslator(tenant_data_dir=repo_dir), allow_missing_metadata=True)

        document = await repo.get(f"file://{markdown_path}")

        assert document is not None
        assert document.metadata.markdown_rel_path == str(markdown_path)
        assert document.metadata.document_key == "external-key"
        assert document.metadata.indexed_at == datetime.fromisoformat("2024-02-03T01:02:03")

    @pytest.mark.asyncio
    async def test_fake_repository_delete_missing_returns_false(self):
        """FakeRepository.delete() should return False when nothing is removed."""

        repo = FakeRepository()
        assert await repo.delete("https://example.com/missing") is False

    @pytest.mark.asyncio
    async def test_fake_repository_deletion_helpers_delegate(self):
        """Helper deletion methods should call delete() and mirror its response."""

        repo = FakeRepository()
        doc = Document.create(url="https://example.com/fake", title="Fake", markdown="# Fake", text="", excerpt="")

        await repo.add(doc)
        assert await repo.delete_by_path_builder(doc.url.value) is True
        assert await repo.count() == 0

        # Second helper call after deletion should still execute and return False
        assert await repo.delete_by_url_translator(doc.url.value) is False

    @pytest.mark.asyncio
    async def test_dual_mode_add_writes_to_staging_directory(self, tmp_path: Path):
        """DualMode repo should stage writes without touching the base storage."""

        base_dir = tmp_path / "base"
        staging_dir = tmp_path / "staging"
        repo = DualModeFileSystemRepository(
            base_dir,
            staging_dir,
            UrlTranslator(tenant_data_dir=base_dir),
        )

        doc = Document.create(url="https://example.com/staged", title="Staged", markdown="# Stage", text="", excerpt="")

        await repo.add(doc)

        assert list(base_dir.rglob("*.md")) == []
        staged_files = list(staging_dir.rglob("*.md"))
        assert len(staged_files) == 1

    @pytest.mark.asyncio
    async def test_dual_mode_reads_lists_and_deletes_from_base(self, tmp_path: Path):
        """DualMode repo delegates read/delete operations to the base repository."""

        base_dir = tmp_path / "base"
        staging_dir = tmp_path / "staging"
        path_builder = PathBuilder()
        repo = DualModeFileSystemRepository(
            base_dir,
            staging_dir,
            UrlTranslator(tenant_data_dir=base_dir),
            path_builder=path_builder,
        )

        doc = Document.create(url="https://example.com/base", title="Base", markdown="# Base", text="", excerpt="")
        await repo.base_repo.add(doc)

        retrieved = await repo.get(doc.url.value)
        assert retrieved is not None
        listed = await repo.list()
        assert listed
        assert listed[0].url.value == doc.url.value
        assert await repo.count() == 1

        assert await repo.delete(doc.url.value) is True
        assert await repo.count() == 0

        await repo.base_repo.add(doc)
        assert await repo.delete_by_path_builder(doc.url.value) is True

    @pytest.mark.asyncio
    async def test_dual_mode_delete_by_url_translator_without_path_builder(self, tmp_path: Path):
        """URLTranslator-based deletions should succeed when no PathBuilder is configured."""

        base_dir = tmp_path / "base"
        staging_dir = tmp_path / "staging"
        repo = DualModeFileSystemRepository(
            base_dir,
            staging_dir,
            UrlTranslator(tenant_data_dir=base_dir),
        )

        doc = Document.create(url="https://example.com/hash", title="Hash", markdown="# Hash", text="", excerpt="")
        await repo.base_repo.add(doc)

        assert await repo.delete_by_url_translator(doc.url.value) is True
