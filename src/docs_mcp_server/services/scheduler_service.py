"""Scheduler service for better modularity and testability."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
import logging
from typing import Any

from ..config import Settings
from ..service_layer.filesystem_unit_of_work import AbstractUnitOfWork
from ..services.cache_service import CacheService
from ..utils.crawl_state_store import CrawlStateStore
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
        metadata_store: CrawlStateStore,
        progress_store: CrawlStateStore,
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
        self._active_trigger_task: asyncio.Task | None = None

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
        if is_dataclass(stats):
            return asdict(stats)
        return {}

    async def get_status_snapshot(self) -> dict[str, Any]:
        """Return scheduler status snapshot, even before initialization."""

        crawl_snapshot = await self.metadata_store.get_status_snapshot()
        fallback_metrics = (
            self._cache_service.get_fetcher_stats()
            if self._cache_service is not None
            else {"fallback_attempts": 0, "fallback_successes": 0, "fallback_failures": 0}
        )
        stats_payload = {
            "mode": None,
            "refresh_schedule": self.refresh_schedule,
            **self.stats,
            **crawl_snapshot,
            **fallback_metrics,
        }

        return {
            "scheduler_running": self.running,
            "scheduler_initialized": self.is_initialized,
            "stats": stats_payload,
        }

    def _parse_iso_timestamp(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

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
        """Trigger an immediate sync cycle without blocking the caller."""

        if not self.is_initialized or self._scheduler is None:
            return {"success": False, "message": "Scheduler not initialized"}

        if self._active_trigger_task and not self._active_trigger_task.done():
            return {"success": False, "message": "Sync already running"}

        task = asyncio.create_task(
            self._scheduler.trigger_sync(
                force_crawler=force_crawler,
                force_full_sync=force_full_sync,
            )
        )
        self._attach_trigger_task(task)

        return {"success": True, "message": "Sync trigger accepted (running asynchronously)"}

    async def trigger_failed_retry(self, *, limit: int | None = None) -> dict:
        """Requeue failed URLs and trigger a sync cycle."""

        if not self.is_initialized or self._scheduler is None:
            return {"success": False, "message": "Scheduler not initialized"}

        if self._active_trigger_task and not self._active_trigger_task.done():
            return {"success": False, "message": "Sync already running"}

        requeued = await self.metadata_store.requeue_failed_urls(limit=limit)
        if requeued == 0:
            return {"success": True, "message": "No failed URLs to retry", "requeued": 0}

        task = asyncio.create_task(self._scheduler.trigger_sync(force_crawler=False, force_full_sync=False))
        self._attach_trigger_task(task)
        return {"success": True, "message": f"Retrying {requeued} failed URLs", "requeued": requeued}

    def _attach_trigger_task(self, task: asyncio.Task) -> None:
        self._active_trigger_task = task

        def _on_complete(completed: asyncio.Task):
            if self._active_trigger_task is completed:
                self._active_trigger_task = None
            try:
                result = completed.result()
            except Exception:  # pragma: no cover - background diagnostics
                logger.error("[%s] Background sync failed", self.tenant_codename, exc_info=True)
                return

            if not isinstance(result, dict) or not result.get("success"):
                logger.warning(
                    "[%s] Background sync returned failure: %s",
                    self.tenant_codename,
                    result,
                )

        task.add_done_callback(_on_complete)
