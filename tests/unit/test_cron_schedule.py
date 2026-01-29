"""Unit tests for cron schedule functionality in deployment config and sync scheduler."""

from datetime import datetime, timezone

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.service_layer.filesystem_unit_of_work import FakeUnitOfWork
from docs_mcp_server.services.cache_service import CacheService
from docs_mcp_server.utils.crawl_state_store import CrawlStateStore
from docs_mcp_server.utils.sync_scheduler import SyncScheduler, SyncSchedulerConfig


@pytest.fixture(autouse=True)
def clean_fake_uow():
    """Clear shared state before/after each test."""
    FakeUnitOfWork.clear_shared_store()
    yield
    FakeUnitOfWork.clear_shared_store()


@pytest.fixture
def uow_factory():
    """Factory for creating FakeUnitOfWork instances."""
    return lambda: FakeUnitOfWork()


@pytest.fixture
def settings():
    """Test settings instance."""
    return Settings(
        docs_name="Test Docs",
        docs_sitemap_url="https://example.com/sitemap.xml",
    )  # type: ignore[call-arg]  # Env vars set in conftest.py


@pytest.fixture
def cache_service_factory(settings, uow_factory):
    """Factory for creating CacheService instances."""

    def factory():
        return CacheService(settings=settings, uow_factory=uow_factory)

    return factory


@pytest.mark.unit
class TestCronScheduleValidation:
    """Test cron schedule validation in TenantConfig."""

    def test_valid_cron_schedule_weekly(self):
        """Test that valid weekly cron schedule is accepted."""
        config = TenantConfig(
            codename="test",
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            refresh_schedule="0 2 * * 1",  # Every Monday at 2am
        )
        assert config.refresh_schedule == "0 2 * * 1"

    def test_valid_cron_schedule_daily(self):
        """Test that valid daily cron schedule is accepted."""
        config = TenantConfig(
            codename="test",
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            refresh_schedule="0 0 * * *",  # Every day at midnight
        )
        assert config.refresh_schedule == "0 0 * * *"

    def test_valid_cron_schedule_every_6_hours(self):
        """Test that valid interval cron schedule is accepted."""
        config = TenantConfig(
            codename="test",
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            refresh_schedule="0 */6 * * *",  # Every 6 hours
        )
        assert config.refresh_schedule == "0 */6 * * *"

    def test_none_refresh_schedule_is_valid(self):
        """Test that None refresh_schedule is valid (manual sync only)."""
        config = TenantConfig(
            codename="test",
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            refresh_schedule=None,
        )
        assert config.refresh_schedule is None

    def test_invalid_cron_schedule_raises_error(self):
        """Test that invalid cron schedule raises validation error."""
        with pytest.raises(ValueError, match="Invalid cron schedule"):
            TenantConfig(
                codename="test",
                docs_name="Test Docs",
                docs_sitemap_url="https://example.com/sitemap.xml",
                refresh_schedule="invalid cron",
            )

    def test_too_many_fields_raises_error(self):
        """Test that cron schedule with too many fields raises error."""
        with pytest.raises(ValueError, match="Invalid cron schedule"):
            TenantConfig(
                codename="test",
                docs_name="Test Docs",
                docs_sitemap_url="https://example.com/sitemap.xml",
                refresh_schedule="0 0 0 * * * *",  # 7 fields (too many)
            )


@pytest.mark.unit
class TestSyncSchedulerWithCron:
    """Test SyncScheduler behavior with cron schedules."""

    def test_scheduler_accepts_cron_schedule(
        self, settings, uow_factory, cache_service_factory, metadata_store, progress_store
    ):
        """Test that scheduler accepts and stores cron schedule."""
        scheduler = SyncScheduler(
            settings=settings,
            uow_factory=uow_factory,
            cache_service_factory=cache_service_factory,
            metadata_store=metadata_store,
            progress_store=progress_store,
            tenant_codename="test-tenant",
            config=SyncSchedulerConfig(
                sitemap_urls=["https://example.com/sitemap.xml"],
                refresh_schedule="0 2 * * 1",
            ),
        )
        assert scheduler.refresh_schedule == "0 2 * * 1"
        assert scheduler.cron_instance is not None

    def test_scheduler_accepts_none_schedule(
        self, settings, uow_factory, cache_service_factory, metadata_store, progress_store
    ):
        """Test that scheduler accepts None schedule (manual sync only)."""
        scheduler = SyncScheduler(
            settings=settings,
            uow_factory=uow_factory,
            cache_service_factory=cache_service_factory,
            metadata_store=metadata_store,
            progress_store=progress_store,
            tenant_codename="test-tenant",
            config=SyncSchedulerConfig(
                sitemap_urls=["https://example.com/sitemap.xml"],
                refresh_schedule=None,
            ),
        )
        assert scheduler.refresh_schedule is None
        assert scheduler.cron_instance is None

    def test_scheduler_rejects_invalid_cron(
        self, settings, uow_factory, cache_service_factory, metadata_store, progress_store
    ):
        """Test that scheduler rejects invalid cron syntax."""
        with pytest.raises(ValueError, match="Invalid cron schedule"):
            SyncScheduler(
                settings=settings,
                uow_factory=uow_factory,
                cache_service_factory=cache_service_factory,
                metadata_store=metadata_store,
                progress_store=progress_store,
                tenant_codename="test-tenant",
                config=SyncSchedulerConfig(
                    sitemap_urls=["https://example.com/sitemap.xml"],
                    refresh_schedule="bad cron",
                ),
            )

    def test_scheduler_stats_include_schedule(
        self, settings, uow_factory, cache_service_factory, metadata_store, progress_store
    ):
        """Test that scheduler stats include the refresh_schedule."""
        scheduler = SyncScheduler(
            settings=settings,
            uow_factory=uow_factory,
            cache_service_factory=cache_service_factory,
            metadata_store=metadata_store,
            progress_store=progress_store,
            tenant_codename="test-tenant",
            config=SyncSchedulerConfig(
                sitemap_urls=["https://example.com/sitemap.xml"],
                refresh_schedule="0 2 * * 1",
            ),
        )
        stats = scheduler.get_stats()
        assert stats["refresh_schedule"] == "0 2 * * 1"

    @pytest.mark.asyncio
    async def test_scheduler_saves_last_sync_time(
        self, settings, uow_factory, cache_service_factory, metadata_store, progress_store
    ):
        """Test that scheduler can save and retrieve last sync time."""
        scheduler = SyncScheduler(
            settings=settings,
            uow_factory=uow_factory,
            cache_service_factory=cache_service_factory,
            metadata_store=metadata_store,
            progress_store=progress_store,
            tenant_codename="test-tenant",
            config=SyncSchedulerConfig(
                sitemap_urls=["https://example.com/sitemap.xml"],
                refresh_schedule="0 2 * * 1",
            ),
        )

        # Save a sync time
        now = datetime.now(timezone.utc)
        await scheduler._save_last_sync_time(now)

        # Retrieve it
        retrieved = await scheduler._get_last_sync_time()
        assert retrieved is not None
        assert abs((retrieved - now).total_seconds()) < 1  # Within 1 second

    @pytest.mark.asyncio
    async def test_scheduler_returns_none_for_missing_sync_time(
        self, settings, uow_factory, cache_service_factory, metadata_store, progress_store
    ):
        """Test that scheduler returns None when no sync time exists."""
        scheduler = SyncScheduler(
            settings=settings,
            uow_factory=uow_factory,
            cache_service_factory=cache_service_factory,
            metadata_store=metadata_store,
            progress_store=progress_store,
            tenant_codename="test-tenant",
            config=SyncSchedulerConfig(
                sitemap_urls=["https://example.com/sitemap.xml"],
                refresh_schedule="0 2 * * 1",
            ),
        )

        # Should return None when no sync time exists
        sync_time = await scheduler._get_last_sync_time()
        assert sync_time is None


@pytest.mark.unit
class TestCronScheduleExamples:
    """Test various cron schedule examples."""

    def test_every_minute(self):
        """Test every minute schedule."""
        config = TenantConfig(
            codename="test",
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            refresh_schedule="* * * * *",
        )
        assert config.refresh_schedule == "* * * * *"

    def test_every_hour(self):
        """Test every hour schedule."""
        config = TenantConfig(
            codename="test",
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            refresh_schedule="0 * * * *",
        )
        assert config.refresh_schedule == "0 * * * *"

    def test_business_hours_weekdays(self):
        """Test business hours on weekdays schedule."""
        config = TenantConfig(
            codename="test",
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            refresh_schedule="0 9-17 * * 1-5",  # 9am-5pm Mon-Fri
        )
        assert config.refresh_schedule == "0 9-17 * * 1-5"

    def test_first_day_of_month(self):
        """Test first day of month schedule."""
        config = TenantConfig(
            codename="test",
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            refresh_schedule="0 0 1 * *",  # Midnight on 1st of month
        )
        assert config.refresh_schedule == "0 0 1 * *"


@pytest.fixture
def metadata_store(tmp_path):
    """Filesystem-backed metadata store for scheduler tests."""

    return CrawlStateStore(tmp_path / "store")


@pytest.fixture
def progress_store(tmp_path):
    """Filesystem-backed sync progress store for scheduler tests."""

    storage_root = tmp_path / "tenant"
    storage_root.mkdir()
    return CrawlStateStore(storage_root)
