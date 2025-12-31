"""Unit tests for FileSystemUnitOfWork.

Following Cosmic Python Chapter 6: Unit of Work Pattern
- Tests FileSystemUnitOfWork transaction boundaries
- Tests staging and commit logic
- Tests rollback behavior
"""

from pathlib import Path

import pytest

from docs_mcp_server.domain.model import Document
from docs_mcp_server.service_layer.filesystem_unit_of_work import (
    STAGING_DIR_PREFIX,
    FileSystemUnitOfWork,
    cleanup_orphaned_staging_dirs,
)
from docs_mcp_server.utils.path_builder import PathBuilder
from docs_mcp_server.utils.url_translator import UrlTranslator


def _get_staging_dirs(base_dir: Path) -> list[Path]:
    """Get all staging directories in base_dir (both legacy and UUID-based)."""
    return [
        entry
        for entry in base_dir.iterdir()
        if entry.is_dir() and (entry.name == ".staging" or entry.name.startswith(STAGING_DIR_PREFIX))
    ]


@pytest.mark.unit
class TestFileSystemUnitOfWork:
    """Test FileSystemUnitOfWork implementation."""

    @pytest.fixture
    def base_dir(self, tmp_path: Path) -> Path:
        """Create temporary base directory for UoW."""
        dir_path = tmp_path / "uow_test"
        dir_path.mkdir()
        return dir_path

    @pytest.fixture
    def url_translator(self, base_dir: Path) -> UrlTranslator:
        """Create UrlTranslator instance."""
        return UrlTranslator(tenant_data_dir=base_dir)

    @pytest.fixture
    def path_builder(self) -> PathBuilder:
        """Create PathBuilder instance for deterministic paths."""
        return PathBuilder()

    @pytest.mark.asyncio
    async def test_creates_staging_directory_on_enter(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Test UoW creates unique UUID-based staging directory when entering context."""
        uow = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)

        async with uow:
            # Staging directory should exist with UUID pattern
            assert uow.staging_dir.exists()
            assert uow.staging_dir.is_dir()
            assert uow.staging_dir.name.startswith(STAGING_DIR_PREFIX)

    @pytest.mark.asyncio
    async def test_cleans_up_staging_on_exit(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Test UoW cleans up its own staging directory on exit."""
        uow = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)

        async with uow:
            staging_dir = uow.staging_dir
            assert staging_dir.exists()

        # After exiting context, this UoW's staging should be cleaned up (rollback)
        assert not staging_dir.exists()

    @pytest.mark.asyncio
    async def test_commit_moves_files_to_base_dir(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Test commit moves files from staging to base directory."""
        doc = Document.create(
            url="https://example.com/test", title="Test Doc", markdown="# Test", text="Test", excerpt=""
        )

        uow = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        # Files should be in base_dir, not .staging
        md_files = list(base_dir.rglob("*.md"))
        meta_files = list(base_dir.rglob("*.meta.json"))

        expected_markdown = path_builder.build_markdown_path(doc.url.value, relative_to=base_dir)
        expected_metadata = path_builder.build_metadata_path(expected_markdown, relative_to=base_dir)

        assert len(md_files) == 1
        assert len(meta_files) == 1
        assert expected_markdown.exists()
        assert expected_metadata.exists()
        assert not (base_dir / ".staging").exists()

    @pytest.mark.asyncio
    async def test_rollback_deletes_staging(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Test rollback deletes staging directory."""
        doc = Document.create(
            url="https://example.com/test", title="Test Doc", markdown="# Test", text="Test", excerpt=""
        )

        uow = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)
        async with uow:
            await uow.documents.add(doc)
            # Explicitly rollback without commit

        # Nothing should be in base_dir
        md_files = list(base_dir.rglob("*.md"))
        meta_files = list(base_dir.rglob("*.meta.json"))

        assert len(md_files) == 0
        assert len(meta_files) == 0
        assert not (base_dir / ".staging").exists()

    @pytest.mark.asyncio
    async def test_automatic_rollback_on_exception(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Test UoW automatically rolls back on exception."""
        doc = Document.create(
            url="https://example.com/test", title="Test Doc", markdown="# Test", text="Test", excerpt=""
        )

        uow = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)
        try:
            async with uow:
                await uow.documents.add(doc)
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Nothing should be committed
        md_files = list(base_dir.rglob("*.md"))
        assert len(md_files) == 0
        assert not (base_dir / ".staging").exists()

    @pytest.mark.asyncio
    async def test_commit_overwrites_existing_files(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Test commit overwrites existing files in base directory."""
        # First transaction: create document
        doc1 = Document.create(
            url="https://example.com/test", title="Original Title", markdown="# Original", text="Original", excerpt=""
        )

        uow1 = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)
        async with uow1:
            await uow1.documents.add(doc1)
            await uow1.commit()

        # Second transaction: update document
        doc2 = Document.create(
            url="https://example.com/test", title="Updated Title", markdown="# Updated", text="Updated", excerpt=""
        )

        uow2 = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)
        async with uow2:
            await uow2.documents.add(doc2)
            await uow2.commit()

        # Verify updated version - need to create new UoW AFTER commit
        # FileSystemUnitOfWork needs the files to be in base_dir, not staging
        uow3 = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)

        # Wait for staging to be set up
        async with uow3:
            # The repository reads from staging, but we committed to base_dir
            # So we need to check base_dir directly
            pass

        # Check files directly in base_dir
        md_files = list(base_dir.rglob("*.md"))
        assert len(md_files) == 1

        # Read the content to verify update
        content = md_files[0].read_text()
        assert "# Updated" in content

    @pytest.mark.asyncio
    async def test_commit_preserves_unrelated_documents(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Ensure committing a new doc does not delete existing siblings."""

        doc_a = Document.create(url="https://example.com/doc-a", title="Doc A", markdown="# A", text="A", excerpt="")
        doc_b = Document.create(url="https://example.com/doc-b", title="Doc B", markdown="# B", text="B", excerpt="")

        uow_initial = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)
        async with uow_initial:
            await uow_initial.documents.add(doc_a)
            await uow_initial.documents.add(doc_b)
            await uow_initial.commit()

        doc_c = Document.create(url="https://example.com/doc-c", title="Doc C", markdown="# C", text="C", excerpt="")

        uow_follow_up = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)
        async with uow_follow_up:
            await uow_follow_up.documents.add(doc_c)
            await uow_follow_up.commit()

        expected_paths = [
            path_builder.build_markdown_path(doc.url.value, relative_to=base_dir) for doc in (doc_a, doc_b, doc_c)
        ]

        for path in expected_paths:
            assert path.exists(), f"Expected markdown for {path.stem} to persist"
            metadata_path = path_builder.build_metadata_path(path.relative_to(base_dir), relative_to=base_dir)
            assert metadata_path.exists(), f"Expected metadata for {path.stem} to persist"

    @pytest.mark.asyncio
    async def test_multiple_documents_in_single_transaction(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Test multiple documents can be added in single transaction."""
        doc1 = Document.create(
            url="https://example.com/doc1", title="Doc 1", markdown="# Doc 1", text="Doc 1", excerpt=""
        )
        doc2 = Document.create(
            url="https://example.com/doc2", title="Doc 2", markdown="# Doc 2", text="Doc 2", excerpt=""
        )

        uow = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)
        async with uow:
            await uow.documents.add(doc1)
            await uow.documents.add(doc2)
            await uow.commit()

        # Verify both documents committed
        md_files = list(base_dir.rglob("*.md"))
        assert len(md_files) == 2

    @pytest.mark.asyncio
    async def test_uuid_staging_isolation(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Test that each UoW gets its own unique staging directory.

        This is the key fix for the race condition bug where multiple async tasks
        were fighting over the same .staging directory.
        """
        uow1 = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)
        uow2 = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)

        async with uow1, uow2:
            # Each UoW should have a different staging directory
            assert uow1.staging_dir != uow2.staging_dir
            assert uow1.staging_dir.exists()
            assert uow2.staging_dir.exists()
            assert uow1.staging_dir.name.startswith(STAGING_DIR_PREFIX)
            assert uow2.staging_dir.name.startswith(STAGING_DIR_PREFIX)

    @pytest.mark.asyncio
    async def test_cleanup_orphaned_staging_dirs(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Test cleanup of orphaned staging directories from crashed processes."""
        import time

        # Create orphaned staging directories (simulating crashed processes)
        legacy_staging = base_dir / ".staging"
        legacy_staging.mkdir()
        (legacy_staging / "orphan.txt").write_text("orphaned file")

        uuid_staging = base_dir / f"{STAGING_DIR_PREFIX}abc12345"
        uuid_staging.mkdir()
        (uuid_staging / "orphan2.txt").write_text("another orphaned file")

        # Set modification time to be old enough for cleanup
        old_time = time.time() - (2 * 3600)  # 2 hours ago
        import os

        os.utime(legacy_staging, (old_time, old_time))
        os.utime(uuid_staging, (old_time, old_time))

        # Run cleanup with 1 hour max age
        cleaned = cleanup_orphaned_staging_dirs(base_dir, max_age_hours=1.0)

        assert cleaned == 2
        assert not legacy_staging.exists()
        assert not uuid_staging.exists()

    @pytest.mark.asyncio
    async def test_repository_accessible_in_context(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Test repository is accessible within UoW context."""
        uow = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)

        async with uow:
            assert uow.documents is not None
            count = await uow.documents.count()
            assert count == 0

    @pytest.mark.asyncio
    async def test_transaction_isolation(
        self, base_dir: Path, url_translator: UrlTranslator, path_builder: PathBuilder
    ):
        """Test changes in one UoW don't affect another before commit."""
        doc = Document.create(
            url="https://example.com/test", title="Test Doc", markdown="# Test", text="Test", excerpt=""
        )

        # UoW 1: Add document but don't commit
        uow1 = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)
        async with uow1:
            await uow1.documents.add(doc)
            # No commit - should rollback

        # UoW 2: Should not see the document
        uow2 = FileSystemUnitOfWork(base_dir, url_translator, path_builder=path_builder)
        async with uow2:
            retrieved = await uow2.documents.get("https://example.com/test")
            assert retrieved is None
