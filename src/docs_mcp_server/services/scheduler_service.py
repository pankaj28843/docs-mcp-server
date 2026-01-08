"""Scheduler service for better modularity and testability."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timezone
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
        return {}

    async def get_status_snapshot(self) -> dict[str, Any]:
        """Return scheduler status snapshot, even before initialization."""

        scheduler = self._scheduler
        if scheduler is not None:
            stats = getattr(scheduler, "stats", {})
            stats_payload = stats if isinstance(stats, dict) else {}
        else:
            metadata_entries = await self.metadata_store.list_all_metadata()
            summary = self._summarize_metadata_entries(metadata_entries)
            storage_doc_count = await self._get_storage_doc_count()
            fallback_metrics = (
                self._cache_service.get_fetcher_stats()
                if self._cache_service is not None
                else {"fallback_attempts": 0, "fallback_successes": 0, "fallback_failures": 0}
            )

            stats_payload = {
                "mode": None,
                "refresh_schedule": self.refresh_schedule,
                "scheduler_running": False,
                "scheduler_initialized": False,
                "storage_doc_count": storage_doc_count,
                "queue_depth": 0,
                **summary,
                **fallback_metrics,
            }

        return {
            "scheduler_running": self.running,
            "scheduler_initialized": self.is_initialized,
            "stats": stats_payload,
        }

    async def _get_storage_doc_count(self) -> int:
        try:
            async with self.uow_factory() as uow:
                return await uow.documents.count()
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.debug("Failed to query document count: %s", exc)
            return 0

    def _summarize_metadata_entries(self, metadata_entries: list[dict]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        total = len(metadata_entries)
        due = 0
        success = 0
        failure_count = 0
        failure_entries: list[dict[str, Any]] = []
        metadata_sample: list[tuple[datetime | None, dict[str, Any]]] = []
        first_seen: datetime | None = None
        last_success: datetime | None = None

        for payload in metadata_entries:
            next_due = self._parse_iso_timestamp(payload.get("next_due_at"))
            if next_due and next_due <= now:
                due += 1

            last_status = payload.get("last_status")
            if last_status == "success":
                success += 1
                fetched_at = self._parse_iso_timestamp(payload.get("last_fetched_at"))
                if fetched_at and (last_success is None or fetched_at > last_success):
                    last_success = fetched_at
            elif last_status == "failed":
                failure_count += 1
                failure_entries.append(
                    {
                        "url": payload.get("url"),
                        "reason": payload.get("last_failure_reason"),
                        "last_failure_at": payload.get("last_failure_at"),
                        "retry_count": payload.get("retry_count", 0),
                    }
                )

            sample_entry = {
                "url": payload.get("url"),
                "last_status": last_status,
                "last_fetched_at": payload.get("last_fetched_at"),
                "next_due_at": payload.get("next_due_at"),
                "retry_count": payload.get("retry_count", 0),
            }
            metadata_sample.append((self._parse_iso_timestamp(payload.get("next_due_at")), sample_entry))

            first_seen_at = self._parse_iso_timestamp(payload.get("first_seen_at"))
            if first_seen_at and (first_seen is None or first_seen_at < first_seen):
                first_seen = first_seen_at

        metadata_sample.sort(key=lambda item: item[0] or datetime.max.replace(tzinfo=timezone.utc))
        trimmed_sample = [entry for _, entry in metadata_sample[:5]]

        summary = {
            "metadata_total_urls": total,
            "metadata_due_urls": due,
            "metadata_successful": success,
            "metadata_pending": max(total - success, 0),
            "metadata_first_seen_at": first_seen.isoformat() if first_seen else None,
            "metadata_last_success_at": last_success.isoformat() if last_success else None,
            "metadata_sample": trimmed_sample,
            "failed_url_count": failure_count,
            "failure_sample": failure_entries[:5],
        }
        return summary

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

        scheduler = self._scheduler

        task = asyncio.create_task(
            scheduler.trigger_sync(
                force_crawler=force_crawler,
                force_full_sync=force_full_sync,
            )
        )
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

        return {"success": True, "message": "Sync trigger accepted (running asynchronously)"}
