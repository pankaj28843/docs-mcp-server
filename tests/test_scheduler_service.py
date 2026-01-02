"""Tests for SchedulerService."""

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
        assert scheduler_service._init_attempted is False

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

        scheduler_service._scheduler = MagicMock()
        assert scheduler_service.is_initialized is True

    @pytest.mark.unit
    def test_scheduler_property(self, scheduler_service):
        """Test scheduler property."""
        assert scheduler_service.scheduler is None

        mock_scheduler = MagicMock()
        scheduler_service._scheduler = mock_scheduler
        assert scheduler_service.scheduler == mock_scheduler

    @pytest.mark.unit
    def test_running_property(self, scheduler_service):
        """Scheduler reports running status from underlying sync loop."""

        assert scheduler_service.running is False

        mock_scheduler = MagicMock()
        mock_scheduler.running = True
        scheduler_service._scheduler = mock_scheduler

        assert scheduler_service.running is True

    @pytest.mark.unit
    def test_stats_property(self, scheduler_service):
        """Scheduler stats default to empty dict before initialization."""

        assert scheduler_service.stats == {}

        mock_scheduler = MagicMock()
        mock_scheduler.stats = {"mode": "sitemap"}
        scheduler_service._scheduler = mock_scheduler

        assert scheduler_service.stats == {"mode": "sitemap"}

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
