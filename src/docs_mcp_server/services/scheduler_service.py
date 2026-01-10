"""Crawler scheduler service built on top of shared lifecycle base."""

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
from .base_scheduler_service import BaseSchedulerService


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SchedulerServiceConfig:
    """Configuration for SchedulerService injection."""

    sitemap_urls: list[str] | None = None
    entry_urls: list[str] | None = None
    refresh_schedule: str | None = None
    enabled: bool = True


class SchedulerService(BaseSchedulerService):
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
        super().__init__(
            mode="crawler",
            refresh_schedule=resolved_config.refresh_schedule,
            enabled=resolved_config.enabled,
            run_triggers_in_background=True,
            manage_cron_loop=False,
        )
        self.settings = settings
        self.uow_factory = uow_factory
        self.metadata_store = metadata_store
        self.progress_store = progress_store
        self.tenant_codename = tenant_codename
        self.sitemap_urls = resolved_config.sitemap_urls or []
        self.entry_urls = resolved_config.entry_urls or []
        self._on_sync_complete = on_sync_complete

        self._scheduler: SyncScheduler | None = None
        self._cache_service: CacheService | None = None

    def _get_cache_service(self) -> CacheService:
        """Factory for creating or retrieving a CacheService instance."""
        if self._cache_service is None:
            self._cache_service = CacheService(
                settings=self.settings,
                uow_factory=self.uow_factory,
            )
        return self._cache_service

    async def _load_metadata_summary_payload(self) -> dict[str, Any]:
        summary = await self.metadata_store.load_summary()
        if not summary:
            return {
                "metadata_total_urls": 0,
                "metadata_due_urls": 0,
                "metadata_successful": 0,
                "metadata_pending": 0,
                "metadata_first_seen_at": None,
                "metadata_last_success_at": None,
                "metadata_sample": [],
                "failed_url_count": 0,
                "failure_sample": [],
                "storage_doc_count": 0,
                "metadata_summary_missing": True,
            }
        return {
            "metadata_total_urls": summary.get("total", 0),
            "metadata_due_urls": summary.get("due", 0),
            "metadata_successful": summary.get("successful", 0),
            "metadata_pending": summary.get("pending", 0),
            "metadata_first_seen_at": summary.get("first_seen_at"),
            "metadata_last_success_at": summary.get("last_success_at"),
            "metadata_sample": summary.get("metadata_sample", []),
            "failed_url_count": summary.get("failed_count", 0),
            "failure_sample": summary.get("failure_sample", []),
            "storage_doc_count": summary.get("storage_doc_count", 0),
        }

    async def _initialize_impl(self) -> bool:
        if not self.sitemap_urls and not self.entry_urls:
            logger.warning("No sitemap or entry URLs provided, scheduler disabled")
            return False

        try:
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

            await self._scheduler.start()
            self._running = True
            return True

        except Exception as e:
            logger.error(f"Failed to initialize scheduler: {e}", exc_info=True)
            return False

    async def _stop_impl(self) -> None:
        if self._scheduler is not None:
            await self._scheduler.stop()
            self._scheduler = None

        if self._cache_service:
            await self._cache_service.close()
            self._cache_service = None

    async def _execute_sync_impl(self, *, force_crawler: bool, force_full_sync: bool) -> dict:
        scheduler = self._scheduler
        if scheduler is None:
            return {"success": False, "message": "Scheduler not initialized"}
        return await scheduler.trigger_sync(
            force_crawler=force_crawler,
            force_full_sync=force_full_sync,
        )

    def _extra_stats(self) -> dict[str, Any]:
        scheduler = self._scheduler
        if scheduler is None:
            return {}
        stats = getattr(scheduler, "stats", None)
        if isinstance(stats, dict):
            return stats
        return {}

    async def _build_status_payload(self) -> dict[str, Any]:
        scheduler_stats = self._extra_stats()
        if scheduler_stats:
            return scheduler_stats

        summary_payload = await self._load_metadata_summary_payload()
        fallback_metrics = (
            self._cache_service.get_fetcher_stats()
            if self._cache_service is not None
            else {"fallback_attempts": 0, "fallback_successes": 0, "fallback_failures": 0}
        )

        return {
            "mode": None,
            "refresh_schedule": self.refresh_schedule,
            "scheduler_running": False,
            "scheduler_initialized": False,
            "storage_doc_count": summary_payload.get("storage_doc_count", 0),
            "queue_depth": 0,
            **summary_payload,
            **fallback_metrics,
        }
