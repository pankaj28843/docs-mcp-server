"""Scheduler service for better modularity and testability."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
import logging
from typing import Any

from ..config import Settings
from ..service_layer.filesystem_unit_of_work import AbstractUnitOfWork
from ..services.cache_service import CacheService
from ..utils.sync_metadata_store import SyncMetadataStore
from ..utils.sync_progress_store import SyncProgressStore
from ..utils.sync_scheduler import SyncScheduler, SyncSchedulerConfig


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SchedulerServiceConfig:
    """Configuration for SchedulerService injection."""

    sitemap_urls: list[str] | None = None
    entry_urls: list[str] | None = None
    refresh_schedule: str | None = None
    enabled: bool = True


class SchedulerService:
    """Service for managing documentation synchronization.

    This class provides a testable, injectable service for the sync scheduler,
    following FastMCP and FastAPI dependency injection patterns.
    """

    def __init__(
        self,
        settings: Settings,
        uow_factory: Callable[[], AbstractUnitOfWork],
        metadata_store: SyncMetadataStore,
        progress_store: SyncProgressStore,
        tenant_codename: str,
        *,
        config: SchedulerServiceConfig | None = None,
        on_sync_complete: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ):
        """Initialize scheduler service.

        Args:
            settings: Settings instance with configuration
            uow_factory: Factory function to create a Unit of Work
            metadata_store: Persistent metadata store shared with scheduler
            progress_store: Filesystem-backed store for sync progress checkpoints
            tenant_codename: Tenant identifier used for progress partitioning
            config: Optional SchedulerServiceConfig, defaults to sensible values
            on_sync_complete: Optional async callback invoked after successful sync
        """
        resolved_config = config or SchedulerServiceConfig()
        self.settings = settings
        self.uow_factory = uow_factory
        self.metadata_store = metadata_store
        self.progress_store = progress_store
        self.tenant_codename = tenant_codename
        self.sitemap_urls = resolved_config.sitemap_urls or []
        self.entry_urls = resolved_config.entry_urls or []
        self.refresh_schedule = resolved_config.refresh_schedule
        self.enabled = resolved_config.enabled
        self._on_sync_complete = on_sync_complete

        self._scheduler: SyncScheduler | None = None
        self._init_attempted = False
        self._cache_service: CacheService | None = None

    def _get_cache_service(self) -> CacheService:
        """Factory for creating or retrieving a CacheService instance."""
        if self._cache_service is None:
            self._cache_service = CacheService(
                settings=self.settings,
                uow_factory=self.uow_factory,
            )
        return self._cache_service

    @property
    def is_initialized(self) -> bool:
        """Check if scheduler is initialized."""
        return self._scheduler is not None

    @property
    def scheduler(self) -> SyncScheduler | None:
        """Get scheduler instance if initialized."""
        return self._scheduler

    @property
    def running(self) -> bool:
        """Return True while the underlying SyncScheduler loop is active."""

        scheduler = self._scheduler
        return bool(scheduler and getattr(scheduler, "running", False))

    @property
    def stats(self) -> dict[str, Any]:
        """Expose scheduler stats for status endpoints."""

        scheduler = self._scheduler
        if scheduler is None:
            return {}
        stats = getattr(scheduler, "stats", None)
        if isinstance(stats, dict):
            return stats
        return {}

    async def initialize(self) -> bool:
        """Initialize and start the scheduler.

        Returns:
            True if successful, False otherwise
        """
        # Don't re-initialize if already initialized
        if self.is_initialized:
            logger.debug("Scheduler already initialized, skipping")
            return True

        if not self.enabled:
            logger.debug("Scheduler disabled, skipping initialization")
            return False

        if not self.sitemap_urls and not self.entry_urls:
            logger.warning("No sitemap or entry URLs provided, scheduler disabled")
            return False

        try:
            logger.info("Initializing sync scheduler...")
            scheduler_config = SyncSchedulerConfig(
                sitemap_urls=self.sitemap_urls,
                entry_urls=self.entry_urls,
                refresh_schedule=self.refresh_schedule,
            )

            self._scheduler = SyncScheduler(
                settings=self.settings,
                uow_factory=self.uow_factory,
                cache_service_factory=self._get_cache_service,
                metadata_store=self.metadata_store,
                progress_store=self.progress_store,
                tenant_codename=self.tenant_codename,
                config=scheduler_config,
                on_sync_complete=self._on_sync_complete,
            )

            logger.info("Starting scheduler...")
            await self._scheduler.start()
            logger.info("Sync scheduler started successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize scheduler: {e}", exc_info=True)
            return False

    async def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler is not None:
            await self._scheduler.stop()
            self._scheduler = None

        if self._cache_service:
            await self._cache_service.close()
            self._cache_service = None

    async def trigger_sync(self, *, force_crawler: bool = False, force_full_sync: bool = False) -> dict:
        """Trigger an immediate sync cycle.

        Args:
            force_crawler: Force re-crawl even if cache is fresh
            force_full_sync: Force full sync of all URLs

        Returns:
            Dict with status and message
        """
        if not self.is_initialized or self._scheduler is None:
            return {"success": False, "message": "Scheduler not initialized"}

        return await self._scheduler.trigger_sync(
            force_crawler=force_crawler,
            force_full_sync=force_full_sync,
        )
