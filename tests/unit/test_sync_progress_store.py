"""Unit tests for SyncProgressStore - persistence for SyncProgress.

Tests the filesystem-backed store that persists sync progress,
enabling resume after container restart.

Following TDD: these tests are written FIRST, implementation follows.
"""

import pytest


@pytest.fixture
def progress_store_module():
    """Import the sync progress store module."""
    from docs_mcp_server.utils import sync_progress_store

    return sync_progress_store


@pytest.fixture
def sync_progress_module():
    """Import the sync progress domain module."""
    from docs_mcp_server.domain import sync_progress

    return sync_progress


@pytest.fixture
def store(tmp_path, progress_store_module):
    """Create a SyncProgressStore with temp directory."""
    return progress_store_module.SyncProgressStore(tmp_path)


@pytest.fixture
def sample_progress(sync_progress_module):
    """Create a sample SyncProgress for testing."""
    progress = sync_progress_module.SyncProgress.create_new(tenant_codename="django")
    progress.start_discovery()
    progress.add_discovered_urls(
        {
            "https://example.com/page1/",
            "https://example.com/page2/",
            "https://example.com/page3/",
        }
    )
    progress.start_fetching()
    progress.mark_url_processed("https://example.com/page1/")
    return progress


@pytest.mark.unit
class TestSyncProgressStoreBasics:
    """Basic CRUD operations for SyncProgressStore."""

    @pytest.mark.asyncio
    async def test_save_and_load_progress(self, store, sample_progress, sync_progress_module):
        """Progress can be saved and loaded."""
        await store.save(sample_progress)

        loaded = await store.load(sample_progress.tenant_codename)

        assert loaded is not None
        assert loaded.sync_id == sample_progress.sync_id
        assert loaded.tenant_codename == sample_progress.tenant_codename
        assert loaded.phase == sample_progress.phase
        assert loaded.discovered_urls == sample_progress.discovered_urls
        assert loaded.processed_urls == sample_progress.processed_urls

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, store):
        """Loading nonexistent tenant returns None."""
        loaded = await store.load("nonexistent-tenant")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_save_overwrites_existing(self, store, sync_progress_module):
        """Saving with same tenant overwrites previous."""
        # First save
        progress1 = sync_progress_module.SyncProgress.create_new(tenant_codename="django")
        progress1.start_discovery()
        await store.save(progress1)

        # Second save (different sync_id)
        progress2 = sync_progress_module.SyncProgress.create_new(tenant_codename="django")
        progress2.start_discovery()
        progress2.start_fetching()
        await store.save(progress2)

        # Should get second progress
        loaded = await store.load("django")
        assert loaded.sync_id == progress2.sync_id

    @pytest.mark.asyncio
    async def test_delete_progress(self, store, sample_progress):
        """Progress can be deleted."""
        await store.save(sample_progress)
        assert await store.load(sample_progress.tenant_codename) is not None

        await store.delete(sample_progress.tenant_codename)
        assert await store.load(sample_progress.tenant_codename) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_no_error(self, store):
        """Deleting nonexistent tenant doesn't raise."""
        # Should not raise
        await store.delete("nonexistent-tenant")

    @pytest.mark.asyncio
    async def test_get_latest_for_tenant(self, store, sync_progress_module):
        """Return most recent sync progress for tenant."""
        for i in range(3):
            progress = sync_progress_module.SyncProgress.create_new(tenant_codename="django")
            progress.start_discovery()
            if i < 2:
                progress.mark_completed()
            await store.save(progress)

        latest = await store.get_latest_for_tenant("django")
        assert latest is not None
        assert latest.is_complete is False


@pytest.mark.unit
class TestSyncProgressStoreAtomicity:
    """Tests for atomic operations and crash safety."""

    @pytest.mark.asyncio
    async def test_atomic_save(self, tmp_path, progress_store_module, sample_progress):
        """Save is atomic - partial writes don't corrupt data."""
        store = progress_store_module.SyncProgressStore(tmp_path)

        await store.save(sample_progress)

        # Verify no temp files left behind
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0

        # Verify data integrity
        loaded = await store.load(sample_progress.tenant_codename)
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_concurrent_saves_safe(self, store, sync_progress_module):
        """Concurrent saves to same tenant are safe."""
        import asyncio

        async def save_progress(suffix: str):
            progress = sync_progress_module.SyncProgress.create_new(tenant_codename="django")
            progress.start_discovery()
            progress.add_discovered_urls({f"https://example.com/page-{suffix}/"})
            await store.save(progress)

        # Run concurrent saves
        await asyncio.gather(
            save_progress("a"),
            save_progress("b"),
            save_progress("c"),
        )

        # Should have one valid progress (last writer wins)
        loaded = await store.load("django")
        assert loaded is not None
        assert len(loaded.discovered_urls) == 1


@pytest.mark.unit
class TestSyncProgressStoreFilePaths:
    """Tests for file path handling."""

    @pytest.mark.asyncio
    async def test_uses_correct_file_structure(self, tmp_path, progress_store_module, sync_progress_module):
        """Store uses expected directory/file structure."""
        store = progress_store_module.SyncProgressStore(tmp_path)

        progress = sync_progress_module.SyncProgress.create_new(tenant_codename="my-tenant")
        await store.save(progress)

        # Expected file location
        expected_dir = tmp_path / "__sync_progress"
        expected_file = expected_dir / "my-tenant.json"

        assert expected_dir.exists()
        assert expected_file.exists()

    @pytest.mark.asyncio
    async def test_handles_special_characters_in_tenant(self, tmp_path, progress_store_module, sync_progress_module):
        """Handle tenant names with special characters."""
        store = progress_store_module.SyncProgressStore(tmp_path)

        # Tenant with dashes and underscores
        progress = sync_progress_module.SyncProgress.create_new(tenant_codename="my-special_tenant-v2")
        await store.save(progress)

        loaded = await store.load("my-special_tenant-v2")
        assert loaded is not None
        assert loaded.tenant_codename == "my-special_tenant-v2"
