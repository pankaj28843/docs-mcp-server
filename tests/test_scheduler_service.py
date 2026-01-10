"""Tests for SchedulerService."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.services.scheduler_service import SchedulerService, SchedulerServiceConfig
from docs_mcp_server.utils.sync_metadata_store import SyncMetadataStore
from docs_mcp_server.utils.sync_progress_store import SyncProgressStore


@pytest.fixture
def mock_settings():
    """Create mock Settings instance for testing."""
    settings = MagicMock(spec=Settings)
    settings.docs_sitemap_urls = ["https://example.com/sitemap.xml"]
    settings.docs_entry_urls = ["https://example.com"]
    settings.docs_sync_enabled = True
    return settings


@pytest.fixture
def metadata_store(tmp_path):
    """Temporary metadata store directory for scheduler tests."""

    return SyncMetadataStore(tmp_path / "__scheduler_meta_test")


@pytest.fixture
def progress_store(tmp_path):
    """Temporary sync progress store."""

    storage_root = tmp_path / "tenant"
    storage_root.mkdir()
    return SyncProgressStore(storage_root)


@pytest.fixture
def scheduler_service(mock_settings, metadata_store, progress_store):
    """Create SchedulerService instance for testing."""
    config = SchedulerServiceConfig(
        sitemap_urls=mock_settings.docs_sitemap_urls,
        entry_urls=mock_settings.docs_entry_urls,
        enabled=mock_settings.docs_sync_enabled,
    )
    return SchedulerService(
        settings=mock_settings,
        uow_factory=MagicMock(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="test-tenant",
        config=config,
    )


class TestSchedulerService:
    """Test suite for SchedulerService."""

    @pytest.mark.unit
    def test_initialization(self, scheduler_service, mock_settings):
        """Test service initialization."""
        assert scheduler_service.settings == mock_settings
        assert scheduler_service.enabled == mock_settings.docs_sync_enabled
        assert scheduler_service._scheduler is None

    @pytest.mark.unit
    def test_initialization_disabled(self, metadata_store, progress_store):
        """Test initialization with disabled scheduler."""
        settings = MagicMock(spec=Settings)
        settings.docs_sync_enabled = False
        settings.docs_sitemap_urls = []
        settings.docs_entry_urls = []
        service = SchedulerService(
            settings=settings,
            uow_factory=MagicMock(),
            metadata_store=metadata_store,
            progress_store=progress_store,
            tenant_codename="test-tenant",
            config=SchedulerServiceConfig(enabled=False),
        )
        assert service.enabled is False

    @pytest.mark.unit
    def test_is_initialized_property(self, scheduler_service):
        """Test is_initialized property."""
        assert scheduler_service.is_initialized is False

        scheduler_service._initialized = True  # pylint: disable=protected-access
        assert scheduler_service.is_initialized is True

    @pytest.mark.unit
    def test_running_property(self, scheduler_service):
        """Scheduler reports running status from underlying sync loop."""

        assert scheduler_service.running is False

        scheduler_service._running = True  # pylint: disable=protected-access
        assert scheduler_service.running is True

    @pytest.mark.unit
    def test_stats_property(self, scheduler_service):
        """Scheduler stats default to empty dict before initialization."""

        stats = scheduler_service.stats
        assert stats["mode"] == "crawler"
        assert stats["total_syncs"] == 0
        assert stats["errors"] == 0
        assert stats["last_result"] is None

        mock_scheduler = MagicMock()
        mock_scheduler.stats = {"mode": "sitemap", "queue_depth": 3}
        scheduler_service._scheduler = mock_scheduler

        updated_stats = scheduler_service.stats
        assert updated_stats["mode"] == "sitemap"
        assert updated_stats["queue_depth"] == 3
        assert updated_stats["total_syncs"] == 0

    @pytest.mark.unit
    async def test_initialize_success(self, scheduler_service):
        """Test successful initialization."""
        with patch("docs_mcp_server.services.scheduler_service.SyncScheduler") as mock_sync:
            mock_scheduler = AsyncMock()
            mock_sync.return_value = mock_scheduler

            result = await scheduler_service.initialize()

            assert result is True
            assert scheduler_service._scheduler is not None
            mock_scheduler.start.assert_called_once()

    @pytest.mark.unit
    async def test_initialize_already_attempted(self, scheduler_service):
        """Test initialization when already initialized (idempotent)."""
        # First initialize
        with patch("docs_mcp_server.services.scheduler_service.SyncScheduler") as mock_sync:
            mock_scheduler = AsyncMock()
            mock_sync.return_value = mock_scheduler
            await scheduler_service.initialize()

        # Second initialize should succeed but skip re-initialization
        result = await scheduler_service.initialize()

        assert result is True  # Returns True because already initialized

    @pytest.mark.unit
    async def test_initialize_disabled(self, metadata_store, progress_store):
        """Test initialization when disabled."""
        settings = MagicMock(spec=Settings)
        settings.docs_sync_enabled = False
        settings.docs_sitemap_urls = []
        settings.docs_entry_urls = []
        service = SchedulerService(
            settings=settings,
            uow_factory=MagicMock(),
            metadata_store=metadata_store,
            progress_store=progress_store,
            tenant_codename="test-tenant",
            config=SchedulerServiceConfig(enabled=False),
        )

        result = await service.initialize()

        assert result is False

    @pytest.mark.unit
    async def test_initialize_no_urls(self, metadata_store, progress_store):
        """Test initialization without URLs."""
        settings = MagicMock(spec=Settings)
        settings.docs_sync_enabled = True
        settings.docs_sitemap_urls = []
        settings.docs_entry_urls = []
        service = SchedulerService(
            settings=settings,
            uow_factory=MagicMock(),
            metadata_store=metadata_store,
            progress_store=progress_store,
            tenant_codename="test-tenant",
            config=SchedulerServiceConfig(sitemap_urls=[], entry_urls=[]),
        )

        result = await service.initialize()

        assert result is False

    @pytest.mark.unit
    async def test_initialize_failure(self, scheduler_service):
        """Test initialization with failure."""
        with patch("docs_mcp_server.services.scheduler_service.SyncScheduler") as mock_sync:
            mock_sync.side_effect = Exception("Initialization error")

            result = await scheduler_service.initialize()

            assert result is False

    @pytest.mark.unit
    async def test_stop_with_scheduler(self, scheduler_service):
        """Test stopping service with active scheduler."""
        mock_scheduler = AsyncMock()
        scheduler_service._scheduler = mock_scheduler

        await scheduler_service.stop()

        mock_scheduler.stop.assert_called_once()
        assert scheduler_service._scheduler is None

    @pytest.mark.unit
    async def test_stop_without_scheduler(self, scheduler_service):
        """Test stopping service without scheduler."""
        await scheduler_service.stop()

        # Should not raise any errors
        assert scheduler_service._scheduler is None

    @pytest.mark.unit
    async def test_get_status_snapshot_before_initialization(self, scheduler_service, metadata_store):
        """Status snapshot should summarize metadata even when scheduler is idle."""

        now = datetime.now(timezone.utc)
        await metadata_store.save_summary(
            {
                "captured_at": now.isoformat(),
                "total": 1,
                "due": 1,
                "successful": 0,
                "pending": 1,
                "first_seen_at": now.isoformat(),
                "last_success_at": None,
                "failed_count": 1,
                "metadata_sample": [
                    {
                        "url": "https://example.com/doc",
                        "last_status": "failed",
                        "last_fetched_at": None,
                        "next_due_at": now.isoformat(),
                        "retry_count": 1,
                    }
                ],
                "failure_sample": [
                    {
                        "url": "https://example.com/doc",
                        "reason": "fallback_failed",
                        "last_failure_at": now.isoformat(),
                        "retry_count": 1,
                    }
                ],
                "storage_doc_count": 5,
            }
        )

        snapshot = await scheduler_service.get_status_snapshot()

        stats = snapshot["stats"]
        assert snapshot["scheduler_running"] is False
        assert snapshot["scheduler_initialized"] is False
        assert stats["metadata_total_urls"] == 1
        assert stats["failed_url_count"] == 1
        assert stats["failure_sample"][0]["reason"] == "fallback_failed"
        assert stats["storage_doc_count"] == 5
        assert "metadata_summary_missing" not in stats

    @pytest.mark.unit
    async def test_get_status_snapshot_uses_scheduler_stats_when_available(self, scheduler_service):
        """Once scheduler is initialized, return live stats instead of summaries."""

        live_stats = {"mode": "sitemap", "failed_url_count": 0}
        mock_scheduler = MagicMock()
        mock_scheduler.stats = live_stats
        mock_scheduler.running = True
        scheduler_service._scheduler = mock_scheduler
        scheduler_service._initialized = True  # pylint: disable=protected-access
        scheduler_service._running = True  # pylint: disable=protected-access

        snapshot = await scheduler_service.get_status_snapshot()

        assert snapshot["scheduler_running"] is True
        assert snapshot["scheduler_initialized"] is True
        assert snapshot["stats"] is live_stats

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_trigger_sync_runs_in_background(self, scheduler_service):
        """Trigger requests should schedule background tasks and return immediately."""

        mock_scheduler = MagicMock()
        mock_scheduler.trigger_sync = AsyncMock(return_value={"success": True, "message": "done"})
        scheduler_service._scheduler = mock_scheduler
        scheduler_service._initialized = True  # pylint: disable=protected-access

        with patch("docs_mcp_server.services.base_scheduler_service.asyncio.create_task") as create_task:
            fake_task = MagicMock()
            fake_task.done.return_value = True
            create_task.return_value = fake_task

            result = await scheduler_service.trigger_sync(force_crawler=True, force_full_sync=True)

        assert result["success"] is True
        assert "running asynchronously" in result["message"]
        create_task.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_trigger_sync_rejects_when_already_running(self, scheduler_service):
        """Subsequent trigger attempts should fail while a task is in-flight."""

        mock_scheduler = MagicMock()
        scheduler_service._scheduler = mock_scheduler
        scheduler_service._initialized = True  # pylint: disable=protected-access

        pending_task = MagicMock()
        pending_task.done.return_value = False
        scheduler_service._active_trigger_task = pending_task

        result = await scheduler_service.trigger_sync()

        assert result == {"success": False, "message": "Sync already running"}
