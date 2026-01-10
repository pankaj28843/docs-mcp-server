"""Continuous documentation synchronization scheduler.

This module implements cron-based or interval-based sitemap crawling,
recursive link discovery, and metadata-driven sync scheduling.

Sync behavior:
- If refresh_schedule (cron) is provided: Sync only at scheduled times
- If refresh_schedule is None: Only manual sync via endpoint (no automatic sync)
- Scheduler checks every minute if a sync is due based on schedule and last sync time
"""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
import socket
from typing import TYPE_CHECKING, Any

from cron_converter import Cron
import httpx
from lxml import etree  # type: ignore[import-untyped]

from ..config import Settings
from ..domain.sync_progress import SyncPhase, SyncProgress
from ..utils.models import SitemapEntry
from ..utils.sync_discovery_runner import SyncDiscoveryRunner
from ..utils.sync_metadata_store import LockLease, SyncMetadataStore
from ..utils.sync_progress_store import SyncProgressStore


if TYPE_CHECKING:
    from ..service_layer.filesystem_unit_of_work import AbstractUnitOfWork
    from ..services.cache_service import CacheService


logger = logging.getLogger(__name__)

SITEMAP_SNAPSHOT_ID = "current_sitemap"
CRAWLER_LOCK_NAME = "crawler"


@dataclass(slots=True)
class SyncSchedulerConfig:
    """Configuration payload for SyncScheduler."""

    sitemap_urls: list[str] | None = None
    entry_urls: list[str] | None = None
    refresh_schedule: str | None = None


class SyncMetadata:
    """Metadata for tracking URL synchronization state."""

    def __init__(  # noqa: PLR0913 - metadata needs explicit fields for clarity
        self,
        url: str,
        discovered_from: str | None = None,
        first_seen_at: datetime | None = None,
        last_fetched_at: datetime | None = None,
        next_due_at: datetime | None = None,
        last_status: str = "pending",
        retry_count: int = 0,
        last_failure_reason: str | None = None,
        last_failure_at: datetime | None = None,
    ):
        self.url = url
        self.discovered_from = discovered_from
        self.first_seen_at = first_seen_at or datetime.now(timezone.utc)
        self.last_fetched_at = last_fetched_at
        self.next_due_at = next_due_at or datetime.now(timezone.utc)
        self.last_status = last_status
        self.retry_count = retry_count
        self.last_failure_reason = last_failure_reason
        self.last_failure_at = last_failure_at

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "discovered_from": self.discovered_from,
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_fetched_at": self.last_fetched_at.isoformat() if self.last_fetched_at else None,
            "next_due_at": self.next_due_at.isoformat(),
            "last_status": self.last_status,
            "retry_count": self.retry_count,
            "last_failure_reason": self.last_failure_reason,
            "last_failure_at": self.last_failure_at.isoformat() if self.last_failure_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SyncMetadata":
        return cls(
            url=data["url"],
            discovered_from=data.get("discovered_from"),
            first_seen_at=datetime.fromisoformat(data["first_seen_at"]),
            last_fetched_at=datetime.fromisoformat(data["last_fetched_at"]) if data.get("last_fetched_at") else None,
            next_due_at=datetime.fromisoformat(data["next_due_at"]),
            last_status=data.get("last_status", "pending"),
            retry_count=data.get("retry_count", 0),
            last_failure_reason=data.get("last_failure_reason"),
            last_failure_at=datetime.fromisoformat(data["last_failure_at"]) if data.get("last_failure_at") else None,
        )


@dataclass
class SyncSchedulerStats:
    """Statistics and state tracking for sync scheduler operations.

    Replaces untyped dict with typed dataclass for better IDE support,
    type safety, and reduced boilerplate in __init__.
    """

    # Configuration
    mode: str = ""
    refresh_schedule: str | None = None
    schedule_interval_hours: float = 24.0
    schedule_interval_hours_effective: float = 24.0

    # Sync counters
    total_syncs: int = 0
    last_sync_at: str | None = None
    next_sync_at: str | None = None

    # URL processing counters
    urls_processed: int = 0
    urls_discovered: int = 0
    urls_cached: int = 0
    urls_fetched: int = 0
    urls_skipped: int = 0
    urls_failed: int = 0
    errors: int = 0
    queue_depth: int = 0
    filtered_urls: int = 0
    es_cached_count: int = 0

    # Sitemap stats
    sitemap_total_urls: int = 0
    storage_doc_count: int = 0

    # Crawler stats
    last_crawler_run: str | None = None
    crawler_total_runs: int = 0
    crawler_lock_status: str = "unlocked"
    crawler_lock_owner: str | None = None
    crawler_lock_expires_at: str | None = None

    # Discovery stats
    discovery_root_urls: int = 0
    discovery_discovered: int = 0
    discovery_filtered: int = 0
    discovery_progressively_processed: int = 0
    discovery_sample: list[str] = field(default_factory=list)

    # Metadata stats
    metadata_total_urls: int = 0
    metadata_due_urls: int = 0
    metadata_successful: int = 0
    metadata_pending: int = 0
    metadata_first_seen_at: str | None = None
    metadata_last_success_at: str | None = None
    metadata_snapshot_path: str | None = None
    metadata_sample: list[str] = field(default_factory=list)

    # Sync control
    force_full_sync_active: bool = False

    # Failure tracking
    failed_url_count: int = 0
    failure_sample: list[str] = field(default_factory=list)

    # Fallback extractor stats
    fallback_attempts: int = 0
    fallback_successes: int = 0
    fallback_failures: int = 0


@dataclass(slots=True)
class SitemapMetadata:
    """Sitemap snapshot summary persisted between scheduler runs."""

    total_urls: int = 0
    filtered_urls: int = 0
    last_fetched: str | None = None
    content_hash: str | None = None

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "SitemapMetadata":
        return cls(
            total_urls=snapshot.get("entry_count", 0),
            filtered_urls=snapshot.get("filtered_count", 0),
            last_fetched=snapshot.get("fetched_at"),
            content_hash=snapshot.get("content_hash"),
        )


@dataclass(slots=True)
class SyncCyclePlan:
    """Captures discovery + metadata inputs for a sync cycle."""

    sitemap_urls: set[str]
    sitemap_lastmod_map: dict[str, str]
    sitemap_changed: bool
    due_urls: set[str]
    has_previous_metadata: bool
    has_documents: bool


@dataclass(slots=True)
class SyncBatchResult:
    """Summary of a batch-processing run."""

    total_urls: int
    processed: int
    failed: int


BatchProcessor = Callable[[str, str | None], Coroutine[Any, Any, None]]
CheckpointHook = Callable[[bool], Coroutine[Any, Any, None]]
FailureHook = Callable[[str, Exception], Coroutine[Any, Any, None]]
SleepHook = Callable[[float], Coroutine[Any, Any, None]]


@dataclass(slots=True)
class SyncBatchRunner:
    """Encapsulates Step 5 batch execution invariants."""

    plan: SyncCyclePlan
    progress: SyncProgress
    process_url: BatchProcessor
    checkpoint: CheckpointHook
    mark_url_failed: FailureHook
    stats: SyncSchedulerStats
    batch_size: int
    sleep_fn: SleepHook

    async def run(self) -> SyncBatchResult:
        self.progress.start_fetching()
        await self.checkpoint(True)

        pending_urls = list(self.progress.pending_urls)
        if not pending_urls:
            logger.info("No URLs queued for processing")
            return SyncBatchResult(total_urls=0, processed=0, failed=0)

        batch_size = max(1, self.batch_size)
        total_urls = len(pending_urls)
        processed = 0
        failed = 0

        async def process_single(url: str):
            try:
                await self.process_url(url, self.plan.sitemap_lastmod_map.get(url))
                self.stats.urls_processed += 1
                return True
            except Exception as exc:
                logger.error(f"Failed to process {url}: {exc}")
                self.stats.errors += 1
                await self.mark_url_failed(url, exc)
                return False

        for index in range(0, total_urls, batch_size):
            batch = pending_urls[index : index + batch_size]
            results = await asyncio.gather(*(process_single(url) for url in batch), return_exceptions=True)
            processed += sum(1 for result in results if result is True)
            failed += sum(1 for result in results if result is not True)

            logger.info("Batch progress: %s/%s processed, %s failed", processed, total_urls, failed)
            await self.checkpoint(False)
            await self.sleep_fn(0.5)

        return SyncBatchResult(total_urls=total_urls, processed=processed, failed=failed)


class SyncScheduler:
    """Orchestrates continuous documentation synchronization with cron-based scheduling."""

    def __init__(
        self,
        settings: Settings,
        uow_factory: "Callable[[], AbstractUnitOfWork]",
        cache_service_factory: "Callable[[], CacheService]",
        metadata_store: SyncMetadataStore,
        progress_store: SyncProgressStore,
        tenant_codename: str,
        *,
        config: SyncSchedulerConfig | None = None,
        on_sync_complete: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ):
        """Initialize sync scheduler.

        Args:
            settings: Settings instance with configuration
            uow_factory: Factory function to create a Unit of Work
            cache_service_factory: Factory to create a CacheService instance
            metadata_store: Metadata persistence for URL schedule state
            progress_store: Progress persistence for resumable syncs
            tenant_codename: Tenant identifier used for logging/stores
            config: Optional SyncSchedulerConfig describing discovery inputs
            on_sync_complete: Optional async callback invoked after successful sync

        Note:
            At least one of sitemap_urls or entry_urls must be provided.
        """
        # Store settings instance
        self.settings = settings
        self.uow_factory = uow_factory
        self.cache_service_factory = cache_service_factory
        self.metadata_store = metadata_store
        self.progress_store = progress_store
        self.tenant_codename = tenant_codename
        self._on_sync_complete = on_sync_complete

        resolved_config = config or SyncSchedulerConfig()

        # Initialize URL lists
        self.sitemap_urls = resolved_config.sitemap_urls or []
        self.entry_urls = resolved_config.entry_urls or []

        if not self.sitemap_urls and not self.entry_urls:
            raise ValueError("At least one of sitemap_urls or entry_urls must be provided")

        # Cron schedule configuration
        self.refresh_schedule = resolved_config.refresh_schedule
        self.cron_instance: Cron | None = self._setup_cron_schedule(self.refresh_schedule)

        self.running = False
        self.task: asyncio.Task | None = None
        self._active_progress: SyncProgress | None = None
        self._last_progress_checkpoint: datetime | None = None
        self._checkpoint_interval = timedelta(seconds=30)

        # Determine mode
        self.mode = self._determine_mode()
        logger.info(f"Sync scheduler initialized in {self.mode} mode")
        if self.sitemap_urls:
            logger.info(f"  Sitemap URLs: {', '.join(self.sitemap_urls)}")
        if self.entry_urls:
            logger.info(f"  Entry URLs: {', '.join(self.entry_urls)}")

        # Global sitemap metadata - loaded on start and every refresh
        self.sitemap_metadata = SitemapMetadata()

        # Calculate schedule interval for idempotent sync checks
        self.schedule_interval_hours = self._calculate_schedule_interval_hours()
        self._crawler_lock_identity = f"{socket.gethostname()}:{os.getpid()}:{id(self)}"

        self._bypass_idempotency = False
        self.stats = SyncSchedulerStats(
            mode=self.mode,
            refresh_schedule=self.refresh_schedule,
            schedule_interval_hours=self.schedule_interval_hours,
            schedule_interval_hours_effective=self.schedule_interval_hours,
        )

    def _determine_mode(self) -> str:
        """Determine the operational mode based on available sources.

        Returns:
            One of: 'sitemap', 'entry', 'hybrid'
        """
        if self.sitemap_urls and self.entry_urls:
            return "hybrid"
        if self.sitemap_urls:
            return "sitemap"
        return "entry"

    def _setup_cron_schedule(self, refresh_schedule: str | None) -> Cron | None:
        """Build Cron instance (if configured) with consistent logging."""
        if not refresh_schedule:
            logger.info("No refresh schedule configured - only manual sync via endpoint")
            return None

        try:
            cron = Cron(refresh_schedule)
        except Exception as exc:
            logger.error(f"Invalid cron schedule '{refresh_schedule}': {exc}")
            raise ValueError(f"Invalid cron schedule: {exc}") from exc

        logger.info(f"Cron schedule configured: {refresh_schedule}")
        return cron

    def _calculate_schedule_interval_hours(self) -> float:
        """Calculate the minimum interval between syncs from cron schedule.

        This enables idempotent sync operations - URLs fetched within this
        interval will be skipped, making it safe to trigger syncs frequently.

        Returns:
            Interval in hours. If no cron schedule, returns 24.0 (daily default).
        """
        if not self.cron_instance:
            # No schedule configured - use default daily interval
            return 24.0

        try:
            # Get two consecutive schedule times to calculate interval
            now = datetime.now(timezone.utc)
            schedule = self.cron_instance.schedule(start_date=now)
            first_run = schedule.next()
            second_run = schedule.next()

            # Calculate interval in hours
            interval_seconds = (second_run - first_run).total_seconds()
            interval_hours = interval_seconds / 3600

            # Enforce minimum 1 hour to prevent excessive fetching
            interval_hours = max(interval_hours, 1.0)

            logger.info(f"Schedule interval calculated: {interval_hours:.1f}h (from cron '{self.refresh_schedule}')")
            return interval_hours

        except Exception as e:
            logger.warning(f"Failed to calculate schedule interval: {e}, using 24h default")
            return 24.0

    async def trigger_sync(self, *, force_crawler: bool = False, force_full_sync: bool = False) -> dict:
        """Trigger an immediate sync cycle.

        This is the public API for manually triggering a sync, used by the
        sync trigger endpoint when running in online mode.

        Args:
            force_crawler: Force re-crawl even if cache is fresh
            force_full_sync: Force full sync of all URLs

        Returns:
            Dict with status and message
        """
        if not self.running:
            return {"success": False, "message": "Scheduler not running"}

        try:
            logger.info("Manual sync triggered (force_crawler=%s, force_full_sync=%s)", force_crawler, force_full_sync)
            await self._sync_cycle(force_crawler=force_crawler, force_full_sync=force_full_sync)
            return {"success": True, "message": "Sync cycle completed"}
        except Exception as e:
            logger.error("Manual sync failed: %s", e, exc_info=True)
            return {"success": False, "message": f"Sync failed: {e}"}

    async def start(self):
        """Start the synchronization scheduler."""
        if self.running:
            logger.warning("Sync scheduler already running")
            return

        logger.info("Starting sync scheduler")

        # Ensure metadata can be accessed
        await self._ensure_metadata_can_be_accessed()

        # Load initial sitemap metadata (only if sitemap URLs are provided)
        if self.sitemap_urls:
            await self._load_sitemap_metadata()

        # Get initial cache count from storage
        await self._update_cache_stats()

        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        logger.info(f"Sync scheduler task created: {self.task}")
        logger.info("Sync scheduler started successfully")

    async def _run_loop(self):
        """Main scheduler loop.

        - If refresh_schedule is set: Checks every minute if sync is due based on cron schedule
        - If refresh_schedule is None: No automatic sync, only manual via endpoint
        """
        # If no schedule configured, just wait indefinitely
        if not self.cron_instance:
            logger.info("No refresh schedule - scheduler idle (sync via endpoint only)")
            # Use Event to wait indefinitely without busy-waiting
            stop_event = asyncio.Event()
            while self.running:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=60.0)
                except TimeoutError:
                    continue  # Check self.running again
            return

        # Cron-based scheduling
        logger.info(f"Scheduler running with cron schedule: {self.refresh_schedule}")

        while self.running:
            try:
                # Check if sync is due
                now = datetime.now(timezone.utc)
                last_sync_time = await self._get_last_sync_time()

                # Calculate next scheduled run based on cron
                assert self.cron_instance is not None, "cron_instance must be initialized"
                schedule = self.cron_instance.schedule(start_date=last_sync_time or now)
                next_run = schedule.next()

                # Update stats with next scheduled time
                self.stats.next_sync_at = next_run.isoformat()

                # If next run is in the past or now, we're due for a sync
                if next_run <= now:
                    logger.info(f"Sync due (last: {last_sync_time}, next: {next_run}, now: {now})")
                    await self._sync_cycle()
                    await self._save_last_sync_time(now)
                    self.stats.total_syncs += 1
                    self.stats.last_sync_at = now.isoformat()
                else:
                    # Calculate sleep time until next check (max 60 seconds)
                    sleep_seconds = min((next_run - now).total_seconds(), 60)
                    logger.debug(
                        f"Next sync at {next_run.isoformat()}, sleeping {sleep_seconds:.0f}s "
                        f"(last sync: {last_sync_time})"
                    )
                    await asyncio.sleep(sleep_seconds)

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)
                self.stats.errors += 1
                await asyncio.sleep(60)  # Back off on error

    async def _get_last_sync_time(self) -> datetime | None:
        """Get the timestamp of the last successful sync."""
        try:
            return await self.metadata_store.get_last_sync_time()
        except Exception as e:
            logger.debug(f"Could not load last sync time: {e}")
            return None

    async def _save_last_sync_time(self, sync_time: datetime):
        """Save the timestamp of the last successful sync."""
        try:
            await self.metadata_store.save_last_sync_time(sync_time)
        except Exception as err:
            logger.debug(f"Failed to persist last sync time: {err}")

    async def _build_cycle_plan(self, *, force_crawler: bool, force_full_sync: bool) -> SyncCyclePlan:
        """Prepare sitemap + metadata context for a sync run."""
        if self.sitemap_urls:
            await self._load_sitemap_metadata()
        await self._update_cache_stats()
        self._refresh_fetcher_metrics()

        blacklist_stats = await self.delete_blacklisted_caches()
        if blacklist_stats.get("deleted", 0) > 0:
            logger.info(
                f"Blacklist cleanup: deleted {blacklist_stats['deleted']} cached documents "
                f"(checked {blacklist_stats['checked']}, errors {blacklist_stats['errors']})"
            )
            await self._update_cache_stats()

        metadata_entries = await self.metadata_store.list_all_metadata()
        await self._write_metadata_snapshot(metadata_entries)
        self._update_metadata_stats(metadata_entries)
        has_previous_metadata = await self._has_previous_metadata(metadata_entries)
        due_urls = await self._get_due_urls(metadata_entries)

        self._bypass_idempotency = force_full_sync or self.stats.metadata_successful == 0
        self.stats.force_full_sync_active = self._bypass_idempotency
        self.stats.schedule_interval_hours_effective = 0.0 if self._bypass_idempotency else self.schedule_interval_hours
        if self._bypass_idempotency:
            reason = "force_full_sync" if force_full_sync else "no_successful_documents"
            logger.info("Idempotency bypass enabled (%s)", reason)

        sitemap_urls: set[str] = set()
        sitemap_lastmod_map: dict[str, str] = {}
        sitemap_changed = True

        if self.mode == "entry":
            logger.info("Entry mode: Using crawler from entry URL")
            sitemap_urls = await self._discover_urls_from_entry(force_crawl=force_crawler)
        elif self.mode == "sitemap":
            logger.info("Sitemap mode: Fetching sitemap")
            sitemap_changed, entries = await self._fetch_and_check_sitemap()
            sitemap_urls, sitemap_lastmod_map = self._extract_urls_from_sitemap(entries)
        else:
            logger.info("Hybrid mode: Using both sitemap and entry URL")
            sitemap_changed, entries = await self._fetch_and_check_sitemap()
            sitemap_urls, sitemap_lastmod_map = self._extract_urls_from_sitemap(entries)
            if self.entry_urls:
                sitemap_urls.update(self.entry_urls)

        logger.info(f"Initial URLs: {len(sitemap_urls)}")
        sitemap_urls = await self._apply_crawler_if_needed(
            sitemap_urls,
            sitemap_changed,
            force_crawler,
            has_previous_metadata=has_previous_metadata,
        )

        logger.info("Step 3: Getting due URLs from metadata...")
        logger.info("Found %s due URLs", len(due_urls))
        has_documents = self.stats.storage_doc_count > 0

        return SyncCyclePlan(
            sitemap_urls=sitemap_urls,
            sitemap_lastmod_map=sitemap_lastmod_map,
            sitemap_changed=sitemap_changed,
            due_urls=due_urls,
            has_previous_metadata=has_previous_metadata,
            has_documents=has_documents,
        )

    async def _hydrate_queue_from_plan(self, *, plan: SyncCyclePlan, progress: SyncProgress) -> None:
        """Populate progress queues based on the prepared cycle plan."""
        discovered_urls = set(plan.sitemap_urls)

        if self.mode == "sitemap" and not plan.sitemap_changed and plan.has_previous_metadata:
            if plan.has_documents:
                logger.info("Sitemap unchanged and URLs already tracked with documents, will only check due URLs")
                discovered_urls = set()
            else:
                logger.info("Sitemap unchanged but no documents found - forcing full resync")

        if discovered_urls:
            progress.add_discovered_urls(discovered_urls)
            await self._checkpoint_progress(force=True)

        progress.enqueue_urls(plan.due_urls)
        self._update_queue_depth_from_progress()

        queue_depth = self.stats.queue_depth
        resumed = max(queue_depth - len(discovered_urls) - len(plan.due_urls), 0)
        logger.info(
            "Step 4: Processing %s URLs (%s from sitemap, %s due, %s resumed)",
            queue_depth,
            len(discovered_urls),
            len(plan.due_urls),
            resumed,
        )

    async def _run_batch_execution(self, *, plan: SyncCyclePlan, progress: SyncProgress) -> SyncBatchResult:
        """Process queued URLs in batches with concurrency control."""

        async def checkpoint(force: bool) -> None:
            await self._checkpoint_progress(force=force)

        async def mark_failed(url: str, error: Exception) -> None:
            await self._mark_url_failed(url, error=error)

        runner = SyncBatchRunner(
            plan=plan,
            progress=progress,
            process_url=self._process_url,
            checkpoint=checkpoint,
            mark_url_failed=mark_failed,
            stats=self.stats,
            batch_size=self.settings.max_concurrent_requests,
            sleep_fn=asyncio.sleep,
        )
        return await runner.run()

    async def _sync_cycle(self, force_crawler: bool = False, force_full_sync: bool = False):
        """Execute one complete synchronization cycle.

        Args:
            force_crawler: If True, force crawler to run regardless of sitemap changes
            force_full_sync: If True, bypass idempotency to refetch every URL once
        """
        logger.info(
            "=== Starting sync cycle (mode: %s, force_crawler=%s, force_full_sync=%s) ===",
            self.mode,
            force_crawler,
            force_full_sync,
        )
        progress = await self._prepare_progress_for_cycle()

        try:
            plan = await self._build_cycle_plan(force_crawler=force_crawler, force_full_sync=force_full_sync)
            await self._hydrate_queue_from_plan(plan=plan, progress=progress)

            # Step 5: Process URLs with concurrency control
            logger.info(f"Step 5: Processing URLs with batch size={self.settings.max_concurrent_requests}")
            batch_result = await self._run_batch_execution(plan=plan, progress=progress)
            logger.info(
                "Step 5 complete: processed %s/%s URLs (%s failed)",
                batch_result.processed,
                batch_result.total_urls,
                batch_result.failed,
            )
            await self._complete_progress()

        except Exception as exc:
            logger.error(f"Sync cycle failed: {exc}", exc_info=True)
            await self._fail_progress(str(exc))
            raise
        finally:
            self._bypass_idempotency = False
            self.stats.force_full_sync_active = False
            self.stats.schedule_interval_hours_effective = self.schedule_interval_hours

    async def _crawl_links_from_roots(self, root_urls: set[str], force_crawl: bool = False) -> set[str]:
        """Crawl links from root URLs to discover all documentation pages.

        Discovered URLs are progressively scheduled for fetching via article-extractor
        as they are found, preventing server overload.

        Implements idempotency: URLs that were recently fetched (within schedule_interval_hours)
        are skipped during crawling since we already have their content and discovered links.
        Use force_crawl=True to bypass this check (useful for debugging).

        Args:
            root_urls: Set of root URLs to crawl from (e.g., https://docs.python.org/3.13/)
            force_crawl: If True, ignore idempotency and crawl all URLs

        Returns:
            Set of all discovered URLs (excluding the roots themselves)
        """
        runner = SyncDiscoveryRunner(
            tenant_codename=self.tenant_codename,
            settings=self.settings,
            metadata_store=self.metadata_store,
            stats=self.stats,
            schedule_interval_hours=self.schedule_interval_hours,
            process_url_callback=self._process_url,
            acquire_crawler_lock_callback=self._acquire_crawler_lock,
        )
        return await runner.run(root_urls, force_crawl)

    async def _acquire_crawler_lock(self) -> LockLease | None:
        """Acquire the crawler lock with TTL enforcement."""

        ttl_seconds = max(60, int(self.settings.crawler_lock_ttl_seconds))
        owner = f"{self._crawler_lock_identity}:{datetime.now(timezone.utc).isoformat()}"

        lease, existing = await self.metadata_store.try_acquire_lock(CRAWLER_LOCK_NAME, owner, ttl_seconds)
        now = datetime.now(timezone.utc)

        if lease:
            self.stats.crawler_lock_status = "acquired"
            self.stats.crawler_lock_owner = lease.owner
            self.stats.crawler_lock_expires_at = lease.expires_at.isoformat()
            return lease

        if existing is None:
            self.stats.crawler_lock_status = "contended"
            self.stats.crawler_lock_owner = None
            self.stats.crawler_lock_expires_at = None
            logger.info("Crawler lock acquisition failed with no metadata; another worker is likely starting")
            return None

        self.stats.crawler_lock_owner = existing.owner
        self.stats.crawler_lock_expires_at = existing.expires_at.isoformat()

        if not existing.is_expired(now=now):
            self.stats.crawler_lock_status = "contended"
            logger.info(
                "Crawler lock held by %s until %s (remaining %.0fs)",
                existing.owner,
                existing.expires_at.isoformat(),
                existing.remaining_seconds(now=now),
            )
            return None

        self.stats.crawler_lock_status = "stale"
        logger.warning(
            "Crawler lock owned by %s expired at %s; evaluating tenant freshness",
            existing.owner,
            existing.expires_at.isoformat(),
        )

        if await self._tenant_recently_refreshed():
            logger.info("Tenant recently refreshed; cleaning up stale lock without rerunning crawler")
            await self.metadata_store.break_lock(CRAWLER_LOCK_NAME)
            return None

        await self.metadata_store.break_lock(CRAWLER_LOCK_NAME)
        lease, _ = await self.metadata_store.try_acquire_lock(CRAWLER_LOCK_NAME, owner, ttl_seconds)
        if lease:
            self.stats.crawler_lock_status = "acquired"
            self.stats.crawler_lock_owner = lease.owner
            self.stats.crawler_lock_expires_at = lease.expires_at.isoformat()
            return lease

        logger.info("Unable to acquire crawler lock after removing stale lease")
        self.stats.crawler_lock_status = "contended"
        return None

    async def _tenant_recently_refreshed(self) -> bool:
        """Check whether the tenant completed a sync within the last schedule interval."""

        last_sync = await self.metadata_store.get_last_sync_time()
        if not last_sync:
            return False

        now = datetime.now(timezone.utc)
        elapsed_hours = (now - last_sync).total_seconds() / 3600
        interval_hours = self.schedule_interval_hours or 24.0
        return elapsed_hours < interval_hours

    async def _fetch_and_check_sitemap(self) -> tuple[bool, list[SitemapEntry]]:
        """Fetch sitemaps and check if any changed."""
        logger.info(f"Fetching {len(self.sitemap_urls)} sitemaps: {', '.join(self.sitemap_urls)}")

        all_entries = []
        any_changed = False
        total_sitemap_urls = 0
        total_filtered_count = 0

        # Use longer timeout for large sitemaps (e.g., Django docs)
        timeout = httpx.Timeout(120.0, connect=30.0)
        headers = {
            "User-Agent": self.settings.get_random_user_agent(),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            # Don't manually set Accept-Encoding - let httpx handle it automatically
            # "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            for sitemap_url in self.sitemap_urls:
                logger.info(f"Fetching sitemap: {sitemap_url}")

                try:
                    resp = await client.get(sitemap_url)
                    resp.raise_for_status()

                    # Debug: Check what we actually received
                    if not resp.content:
                        logger.error(f"Empty response for sitemap {sitemap_url}")
                        continue

                    content_preview = resp.content[:200].decode("utf-8", errors="ignore")
                    logger.info(f"Sitemap response ({len(resp.content)} bytes) starts with: {content_preview[:100]}")

                    # Calculate hash for change detection
                    content_hash = hashlib.sha256(resp.content).hexdigest()

                    # Parse sitemap and count before/after filtering
                    try:
                        root = etree.fromstring(resp.content)
                    except etree.XMLSyntaxError as xml_err:
                        logger.error(f"XML syntax error parsing sitemap {sitemap_url}: {xml_err}")
                        logger.error(f"Content preview: {content_preview}")
                        raise
                    sitemap_total_urls = len(root.findall("{*}url"))
                    total_sitemap_urls += sitemap_total_urls
                    entries = []

                    for url_elem in root.findall("{*}url"):
                        loc = url_elem.find("{*}loc").text

                        # Apply URL filtering
                        if not self.settings.should_process_url(loc):
                            continue

                        lastmod_elem = url_elem.find("{*}lastmod")
                        lastmod = None
                        if lastmod_elem is not None and lastmod_elem.text:
                            try:
                                lastmod = datetime.fromisoformat(lastmod_elem.text.replace("Z", "+00:00"))
                            except Exception:
                                pass
                        entries.append(SitemapEntry(url=loc, lastmod=lastmod))

                    filtered_count = sitemap_total_urls - len(entries)
                    total_filtered_count += filtered_count
                    all_entries.extend(entries)

                    # Check if this sitemap changed
                    sitemap_key = f"sitemap_{hashlib.sha256(sitemap_url.encode()).hexdigest()[:8]}"
                    previous_snapshot = await self._get_sitemap_snapshot(sitemap_key)
                    changed = True

                    if previous_snapshot:
                        previous_hash = previous_snapshot.get("content_hash")
                        changed = previous_hash != content_hash

                    if changed:
                        any_changed = True

                    # Update snapshot with filtered count
                    await self._save_sitemap_snapshot(
                        {
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                            "entry_count": len(entries),
                            "total_urls": sitemap_total_urls,
                            "filtered_count": filtered_count,
                            "content_hash": content_hash,
                            "sitemap_url": sitemap_url,
                        },
                        sitemap_key,
                    )

                    status = "changed" if changed else "unchanged"
                    logger.info(
                        f"Sitemap {sitemap_url} {status}: {len(entries)} entries "
                        f"(filtered {filtered_count} from {sitemap_total_urls})"
                    )

                except etree.XMLSyntaxError as e:
                    logger.error(f"XML parsing error for sitemap {sitemap_url}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error fetching sitemap {sitemap_url}: {e}")
                    continue

        # Also save overall snapshot for backward compatibility
        combined_hash = hashlib.sha256("|".join(self.sitemap_urls).encode()).hexdigest()
        await self._save_sitemap_snapshot(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "entry_count": len(all_entries),
                "total_urls": total_sitemap_urls,
                "filtered_count": total_filtered_count,
                "content_hash": combined_hash,
                "sitemap_count": len(self.sitemap_urls),
            }
        )

        logger.info(
            f"Combined sitemaps: {len(all_entries)} total entries "
            f"(filtered {total_filtered_count} from {total_sitemap_urls})"
        )
        return any_changed, all_entries

    def _extract_urls_from_sitemap(self, entries: list[SitemapEntry]) -> tuple[set[str], dict]:
        """Extract URLs and lastmod map from sitemap entries.

        Args:
            entries: List of sitemap entries

        Returns:
            Tuple of (url_set, lastmod_map)
        """
        sitemap_urls = set()
        sitemap_lastmod_map = {}

        for entry in entries:
            url = str(entry.url)
            sitemap_urls.add(url)
            if entry.lastmod:
                sitemap_lastmod_map[url] = entry.lastmod

        logger.info(f"Extracted {len(sitemap_urls)} URLs from sitemap")
        return sitemap_urls, sitemap_lastmod_map

    async def _resolve_entry_url_redirects(self, entry_urls: list[str]) -> set[str]:
        """Resolve redirects for entry URLs to get final destinations.

        Args:
            entry_urls: List of original entry URLs

        Returns:
            Set of resolved URLs (after following redirects)
        """
        resolved_urls = set()

        # Use longer timeout for initial entry URL resolution
        timeout = httpx.Timeout(60.0, connect=30.0)
        headers = {
            "User-Agent": self.settings.get_random_user_agent(),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            max_parallel = max(1, min(len(entry_urls), 8))
            semaphore = asyncio.Semaphore(max_parallel)
            logger.debug(
                "Resolving %d entry URLs with up to %d concurrent HEAD requests",
                len(entry_urls),
                max_parallel,
            )

            async def resolve_single(url: str) -> str | None:
                async with semaphore:
                    try:
                        resp = await client.head(url)
                        final_url = str(resp.url)

                        if final_url != url:
                            logger.info(f"Entry URL redirect: {url} -> {final_url}")
                        else:
                            logger.debug(f"Entry URL no redirect: {url}")

                        if self.settings.should_process_url(final_url):
                            return final_url

                        logger.warning(
                            "Resolved entry URL %s filtered out by whitelist/blacklist",
                            final_url,
                        )
                        return None

                    except Exception as exc:
                        logger.warning(f"Failed to resolve entry URL {url}: {exc}")
                        if self.settings.should_process_url(url):
                            return url
                        logger.warning(
                            "Original entry URL %s filtered out by whitelist/blacklist",
                            url,
                        )
                        return None

            results = await asyncio.gather(*(resolve_single(url) for url in entry_urls))
            for resolved in results:
                if resolved:
                    resolved_urls.add(resolved)

        return resolved_urls

    async def _discover_urls_from_entry(self, force_crawl: bool = False) -> set[str]:
        """Discover URLs starting from entry point URLs.

        Args:
            force_crawl: If True, bypass idempotency checks and crawl all URLs

        Returns:
            Set of discovered URLs (including the resolved entry URLs)
        """
        if not self.entry_urls:
            return set()

        logger.info(f"Discovering URLs from {len(self.entry_urls)} entry points: {', '.join(self.entry_urls)}")

        # Resolve redirects for entry URLs first
        root_urls = await self._resolve_entry_url_redirects(self.entry_urls)

        if not root_urls:
            logger.warning("No valid entry URLs after redirect resolution and filtering")
            return set()

        logger.info(f"Resolved {len(self.entry_urls)} entry URLs to {len(root_urls)} root URLs")
        if len(root_urls) != len(self.entry_urls):
            logger.info(f"Root URLs after resolution: {', '.join(sorted(root_urls))}")

        # Crawl to discover all linked pages
        discovered_urls = await self._crawl_links_from_roots(root_urls, force_crawl=force_crawl)

        # Include the resolved entry URLs themselves
        all_urls = root_urls.union(discovered_urls)

        logger.info(f"Discovered {len(all_urls)} total URLs from {len(self.entry_urls)} entry points")
        return all_urls

    async def _apply_crawler_if_needed(
        self,
        sitemap_urls: set[str],
        sitemap_changed: bool,
        force_crawler: bool,
        *,
        has_previous_metadata: bool | None = None,
    ) -> set[str]:
        """Apply crawler to discover additional URLs if appropriate.

        Args:
            sitemap_urls: Initial set of URLs from sitemap or entry
            sitemap_changed: Whether sitemap changed
            force_crawler: Whether to force crawler execution
            has_previous_metadata: Optional cached flag avoiding duplicate store scans

        Returns:
            Combined set of URLs after optional crawling
        """
        # Entry mode always crawls (already done in _discover_urls_from_entry)
        if self.mode == "entry":
            return sitemap_urls

        # Check if crawler is enabled
        crawler_enabled = self.settings.enable_crawler
        if not crawler_enabled:
            logger.info("Crawler disabled via ENABLE_CRAWLER=false")
            return sitemap_urls

        if has_previous_metadata is None:
            has_previous_metadata = await self._has_previous_metadata()

        # Check if we should run crawler
        es_cached = self.stats.urls_cached
        filtered_count = self.stats.discovery_filtered

        should_run_crawler = force_crawler or (not has_previous_metadata or es_cached <= filtered_count)

        if not should_run_crawler:
            if sitemap_changed:
                logger.info("Crawler suppressed: sitemap changed but metadata backlog already exists")
            else:
                logger.info("Crawler not needed (cache sufficient and no changes)")
            return sitemap_urls

        # Determine crawler reason for logging
        crawler_reason = []
        if force_crawler:
            crawler_reason.append("forced")
        if not has_previous_metadata:
            if sitemap_changed:
                crawler_reason.append("sitemap changed")
            else:
                crawler_reason.append("no previous metadata")
        if es_cached <= filtered_count:
            crawler_reason.append(f"sparse cache ({es_cached} <= {filtered_count})")

        logger.info(f"Running crawler from {len(sitemap_urls)} root URLs (reason: {', '.join(crawler_reason)})")

        # Crawl to discover additional URLs
        # Pass force_crawler to bypass idempotency checks in the crawler
        previous_runs = self.stats.crawler_total_runs
        discovered_urls = await self._crawl_links_from_roots(sitemap_urls, force_crawl=force_crawler)

        if self.stats.crawler_total_runs == previous_runs:
            self.stats.crawler_total_runs += 1
            self.stats.last_crawler_run = datetime.now(timezone.utc).isoformat()

        logger.info(f"Discovered {len(discovered_urls)} additional URLs via crawling")

        # Update crawler tracking stats
        self.stats.urls_discovered = len(discovered_urls)
        if self.stats.last_crawler_run:
            logger.info(
                f"Crawler stats: total runs={self.stats.crawler_total_runs}, last run={self.stats.last_crawler_run}"
            )
        else:
            logger.info("Crawler run was skipped before completion (lock or error)")

        # Combine root URLs with discovered URLs
        all_urls = sitemap_urls.union(discovered_urls)
        logger.info(f"Total URLs after crawling: {len(all_urls)}")

        return all_urls

    async def _process_url(self, url: str, sitemap_lastmod: datetime | None = None):
        """Process a single URL using the CacheService.

        This method delegates all fetching and caching logic to the CacheService,
        which handles cache checks, TTL, and storage. This scheduler's role
        is to orchestrate which URLs to process and when.

        Implements idempotent sync: URLs fetched within the schedule interval
        will be skipped. This makes it safe to trigger syncs frequently without
        wasting resources re-fetching recently processed URLs.
        """
        logger.debug(f"Processing URL: {url}")

        try:
            # Idempotent check: Skip if URL was fetched within schedule interval
            existing_metadata = await self.metadata_store.load_url_metadata(url)
            if not self._bypass_idempotency and existing_metadata:
                try:
                    metadata = SyncMetadata.from_dict(existing_metadata)
                    if metadata.last_fetched_at and metadata.last_status == "success":
                        now = datetime.now(timezone.utc)
                        age_hours = (now - metadata.last_fetched_at).total_seconds() / 3600
                        if age_hours < self.schedule_interval_hours:
                            logger.debug(
                                f"Skipping {url} - fetched {age_hours:.1f}h ago "
                                f"(interval: {self.schedule_interval_hours:.1f}h)"
                            )
                            self.stats.urls_skipped += 1
                            await self._record_progress_skipped(
                                url,
                                reason=f"recently_fetched_{age_hours:.1f}h",
                            )
                            return
                except Exception as e:
                    logger.debug(f"Could not check metadata for {url}: {e}")
            elif self._bypass_idempotency:
                logger.debug("Bypassing idempotency window for %s", url)

            cache_service = self.cache_service_factory()
            page, was_cached, failure_reason = await cache_service.check_and_fetch_page(
                url,
                use_semantic_cache=not self._bypass_idempotency,
            )
            self._refresh_fetcher_metrics(cache_service)

            if page:
                # Update statistics based on whether it was a cache hit or fresh fetch
                if was_cached:
                    self.stats.urls_cached += 1
                else:
                    self.stats.urls_fetched += 1

                # Calculate next check time based on sitemap lastmod freshness
                next_due = self._calculate_next_due(sitemap_lastmod)

                # Success - reset retry count and update metadata
                await self._update_metadata(
                    url=url,
                    last_fetched_at=datetime.now(timezone.utc),
                    next_due_at=next_due,
                    status="success",
                    retry_count=0,  # Reset on success
                )
                await self._record_progress_processed(url)
                return
            # Failed - mark for retry with exponential backoff
            logger.warning(f"Failed to process {url}")
            await self._mark_url_failed(url, reason=failure_reason or "PageFetchFailed")

        except Exception as e:
            logger.error(f"Unhandled error processing {url}: {e}", exc_info=True)
            self.stats.errors += 1
            await self._mark_url_failed(url, error=e)

    def _calculate_next_due(self, sitemap_lastmod: datetime | None = None) -> datetime:
        """Calculate next sync due date based on sitemap lastmod.

        Strategy:
        - If lastmod is recent (< 7 days): check again in 1 day (content may change soon)
        - If lastmod is moderate (7-30 days): check again in 7 days
        - If lastmod is old (> 30 days): check again in 30 days (stable content)
        - If no lastmod provided: default to 7 days

        This respects content freshness from sitemap while enforcing:
        - Minimum 24-hour interval between actual fetches (enforced by cache.py)
        - Maximum 30-day interval for any content
        """
        now = datetime.now(timezone.utc)

        # If sitemap provides lastmod, use it to determine sync frequency
        if sitemap_lastmod:
            # Ensure sitemap_lastmod is timezone-aware
            if sitemap_lastmod.tzinfo is None:
                sitemap_lastmod = sitemap_lastmod.replace(tzinfo=timezone.utc)

            days_since_mod = (now - sitemap_lastmod).days

            if days_since_mod < 7:
                # Recently modified content - check more frequently (1 day)
                return now + timedelta(days=1)
            if days_since_mod < 30:
                # Moderately fresh content - check every 7 days
                return now + timedelta(days=self.settings.default_sync_interval_days)
            # Stable/old content - check every 30 days
            return now + timedelta(days=self.settings.max_sync_interval_days)

        # No lastmod provided - default to 7 days
        return now + timedelta(days=self.settings.default_sync_interval_days)

    async def _update_metadata(
        self,
        url: str,
        last_fetched_at: datetime,
        next_due_at: datetime,
        status: str,
        retry_count: int,
    ):
        """Update metadata for a URL."""
        existing_payload = await self.metadata_store.load_url_metadata(url)
        existing = SyncMetadata.from_dict(existing_payload) if existing_payload else SyncMetadata(url=url)

        existing.last_fetched_at = last_fetched_at
        existing.next_due_at = next_due_at
        existing.last_status = status
        existing.retry_count = retry_count
        if status == "success":
            existing.last_failure_reason = None
            existing.last_failure_at = None

        await self.metadata_store.save_url_metadata(existing.to_dict())

    async def _mark_url_failed(self, url: str, *, error: Exception | None = None, reason: str | None = None):
        """Mark URL as failed and schedule retry with backoff.

        Uses exponential backoff for retries:
        - 1st retry: 1 hour (may be transient network/firewall issue)
        - 2nd retry: 2 hours
        - 3rd retry: 4 hours
        - 4th+ retry: 8 hours (capped)

        This allows for quick retries when offline or behind bad firewall,
        while still respecting the MIN_FETCH_INTERVAL_HOURS for successful fetches.
        """
        existing_payload = await self.metadata_store.load_url_metadata(url)
        metadata = SyncMetadata.from_dict(existing_payload) if existing_payload else SyncMetadata(url=url)

        metadata.retry_count += 1
        metadata.last_status = "failed"

        failure_timestamp = datetime.now(timezone.utc)
        max_backoff_hours = max(1, self.settings.max_sync_interval_days * 24)
        backoff_hours = min(2 ** (metadata.retry_count - 1), max_backoff_hours)
        metadata.next_due_at = failure_timestamp + timedelta(hours=backoff_hours)
        failure_detail = reason or (str(error) if error else "UnknownError")
        metadata.last_failure_reason = failure_detail
        metadata.last_failure_at = failure_timestamp

        logger.info(
            "Marked %s as failed (attempt %s), retry in %sh (max=%sh)",
            url,
            metadata.retry_count,
            backoff_hours,
            max_backoff_hours,
        )

        await self.metadata_store.save_url_metadata(metadata.to_dict())

        self.stats.urls_failed = self.stats.urls_failed + 1

        error_type = error.__class__.__name__ if error else (reason or "UnknownError")
        error_message = failure_detail
        await self._record_progress_failed(url=url, error_type=error_type, error_message=error_message)

    async def _get_due_urls(self, metadata_entries: list[dict] | None = None) -> set[str]:
        """Get URLs that are due for sync."""
        now = datetime.now(timezone.utc)
        due_urls = set()

        all_metadata = (
            metadata_entries if metadata_entries is not None else await self.metadata_store.list_all_metadata()
        )
        for payload in all_metadata:
            try:
                metadata = SyncMetadata.from_dict(payload)
            except Exception:
                continue

            if metadata.next_due_at <= now:
                due_urls.add(metadata.url)

        return due_urls

    async def _has_previous_metadata(self, metadata_entries: list[dict] | None = None) -> bool:
        """Check if we have any previous metadata, indicating prior sync runs."""
        all_metadata = (
            metadata_entries if metadata_entries is not None else await self.metadata_store.list_all_metadata()
        )
        return len(all_metadata) > 0

    async def _write_metadata_snapshot(self, metadata_entries: list[dict]) -> None:
        """Persist a lightweight snapshot of current metadata for debugging."""
        if not metadata_entries:
            self.stats.metadata_snapshot_path = None
            self.stats.metadata_sample = []
            return

        snapshot_name = "metadata_snapshot_latest"
        snapshot_payload = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "total_entries": len(metadata_entries),
            "schedule_interval_hours": self.schedule_interval_hours,
            "sample": self._select_metadata_sample(metadata_entries, limit=25),
        }
        try:
            await self.metadata_store.save_debug_snapshot(snapshot_name, snapshot_payload)
            snapshot_path = self.metadata_store.metadata_root / f"{snapshot_name}.debug.json"
            self.stats.metadata_snapshot_path = str(snapshot_path)
        except Exception as exc:  # pragma: no cover - debug aid
            logger.debug("Failed to persist metadata snapshot: %s", exc)

    def _update_metadata_stats(self, metadata_entries: list[dict]) -> None:
        """Update in-memory stats from metadata entries."""
        total = len(metadata_entries)
        now = datetime.now(timezone.utc)
        due = 0
        success = 0
        failure_count = 0
        first_seen_at: datetime | None = None
        last_success_at: datetime | None = None
        failure_entries: list[dict[str, Any]] = []

        for payload in metadata_entries:
            try:
                metadata = SyncMetadata.from_dict(payload)
            except Exception:
                continue

            if metadata.next_due_at <= now:
                due += 1

            if metadata.first_seen_at and (first_seen_at is None or metadata.first_seen_at < first_seen_at):
                first_seen_at = metadata.first_seen_at

            if metadata.last_status == "success":
                success += 1
                if metadata.last_fetched_at and (last_success_at is None or metadata.last_fetched_at > last_success_at):
                    last_success_at = metadata.last_fetched_at
            elif metadata.last_status == "failed":
                failure_count += 1
                failure_entries.append(
                    {
                        "url": metadata.url,
                        "reason": metadata.last_failure_reason,
                        "last_failure_at": metadata.last_failure_at.isoformat() if metadata.last_failure_at else None,
                        "retry_count": metadata.retry_count,
                    }
                )

        pending = max(total - success, 0)

        self.stats.metadata_total_urls = total
        self.stats.metadata_due_urls = due
        self.stats.metadata_successful = success
        self.stats.metadata_pending = pending
        self.stats.metadata_first_seen_at = first_seen_at.isoformat() if first_seen_at else None
        self.stats.metadata_last_success_at = last_success_at.isoformat() if last_success_at else None
        self.stats.metadata_sample = self._select_metadata_sample(metadata_entries)
        self.stats.failed_url_count = failure_count
        self.stats.failure_sample = failure_entries[:5]

    def _select_metadata_sample(self, metadata_entries: list[dict], limit: int = 5) -> list[dict[str, Any]]:
        if not metadata_entries or limit <= 0:
            return []

        def sort_key(entry: dict) -> datetime:
            parsed = self._parse_iso_timestamp(entry.get("next_due_at"))
            return parsed or datetime.max.replace(tzinfo=timezone.utc)

        return [
            {
                "url": payload.get("url"),
                "last_status": payload.get("last_status"),
                "last_fetched_at": payload.get("last_fetched_at"),
                "next_due_at": payload.get("next_due_at"),
                "retry_count": payload.get("retry_count", 0),
            }
            for payload in sorted(metadata_entries, key=sort_key)[:limit]
        ]

    def _parse_iso_timestamp(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    async def _load_sitemap_metadata(self):
        """Load sitemap metadata from storage."""
        try:
            snapshot = await self._get_sitemap_snapshot()
            if snapshot:
                self.sitemap_metadata = SitemapMetadata.from_snapshot(snapshot)
                self.stats.sitemap_total_urls = self.sitemap_metadata.total_urls
                logger.info(f"Loaded sitemap metadata: {self.sitemap_metadata.total_urls} URLs")
            else:
                self.sitemap_metadata = SitemapMetadata()
                logger.debug("No sitemap metadata found yet")
        except Exception as e:
            logger.debug(f"Could not load sitemap metadata: {e}")

    async def _update_cache_stats(self):
        """Query storage to get actual cached document count."""
        try:
            async with self.uow_factory() as uow:
                cache_count = await uow.documents.count()
                self.stats.storage_doc_count = cache_count

                sitemap_count = self.sitemap_metadata.total_urls
                if sitemap_count > 0:
                    cache_pct = (cache_count / sitemap_count) * 100
                    logger.info(f"Filesystem storage: {cache_count}/{sitemap_count} URLs ({cache_pct:.1f}%)")
                else:
                    logger.info(f"Filesystem storage: {cache_count} URLs")
        except Exception as e:
            logger.debug(f"Could not query cache count: {e}")

    def _refresh_fetcher_metrics(self, cache_service: "CacheService | None" = None) -> None:
        """Copy cache fetcher fallback metrics into scheduler stats."""

        try:
            service = cache_service or self.cache_service_factory()
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.debug("Failed to access cache service for metrics: %s", exc)
            return

        if service is None:
            return

        try:
            metrics = service.get_fetcher_stats()
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.debug("Failed to retrieve fetcher stats: %s", exc)
            return

        for key in ("fallback_attempts", "fallback_successes", "fallback_failures"):
            try:
                setattr(self.stats, key, int(metrics.get(key, 0)))
            except Exception:
                setattr(self.stats, key, 0)

    async def _ensure_metadata_can_be_accessed(self):
        """Ensure metadata can be accessed by doing a simple count."""
        try:
            async with self.uow_factory() as uow:
                await uow.documents.count()
            self.metadata_store.ensure_ready()
            await self.metadata_store.cleanup_legacy_artifacts()
            logger.info("Metadata storage is accessible.")
        except Exception as e:
            logger.error(f"Failed to access metadata storage: {e}", exc_info=True)
            raise

    async def _get_sitemap_snapshot(self, snapshot_id: str = SITEMAP_SNAPSHOT_ID) -> dict | None:
        """Get the current sitemap snapshot."""
        try:
            return await self.metadata_store.get_sitemap_snapshot(snapshot_id)
        except Exception as err:
            logger.debug(f"Could not load sitemap snapshot {snapshot_id}: {err}")
            return None

    async def _save_sitemap_snapshot(self, snapshot: dict, snapshot_id: str = SITEMAP_SNAPSHOT_ID):
        """Save sitemap snapshot."""
        try:
            await self.metadata_store.save_sitemap_snapshot(snapshot, snapshot_id)
        except Exception as err:
            logger.debug(f"Failed to persist sitemap snapshot {snapshot_id}: {err}")

    async def _load_or_create_progress(self) -> SyncProgress:
        if self._active_progress is not None:
            return self._active_progress

        existing = await self.progress_store.get_latest_for_tenant(self.tenant_codename)
        if existing and existing.can_resume and not existing.is_complete and existing.phase != SyncPhase.FAILED:
            self._active_progress = existing
        else:
            self._active_progress = SyncProgress.create_new(self.tenant_codename)
        return self._active_progress

    async def _prepare_progress_for_cycle(self) -> SyncProgress:
        progress = await self._load_or_create_progress()
        if progress.phase == SyncPhase.INTERRUPTED and progress.can_resume:
            progress.resume()
        elif progress.phase == SyncPhase.INITIALIZING:
            progress.start_discovery()
        await self._checkpoint_progress(force=True, keep_history=True)
        return progress

    async def _checkpoint_progress(self, *, force: bool = False, keep_history: bool = False) -> None:
        if not self._active_progress:
            return
        now = datetime.now(timezone.utc)
        if (
            not force
            and self._last_progress_checkpoint
            and (now - self._last_progress_checkpoint) < self._checkpoint_interval
        ):
            return
        self._last_progress_checkpoint = now
        checkpoint_payload = self._active_progress.create_checkpoint()
        await self.progress_store.save(self._active_progress)
        await self.progress_store.save_checkpoint(
            self.tenant_codename,
            checkpoint_payload,
            keep_history=keep_history,
        )

    def _update_queue_depth_from_progress(self) -> None:
        if self._active_progress:
            self.stats.queue_depth = len(self._active_progress.pending_urls)

    async def _record_progress_processed(self, url: str) -> None:
        if not self._active_progress:
            return
        self._active_progress.mark_url_processed(url)
        self._update_queue_depth_from_progress()
        await self._checkpoint_progress(force=False)

    async def _record_progress_skipped(self, url: str, reason: str) -> None:
        if not self._active_progress:
            return
        self._active_progress.mark_url_skipped(url, reason)
        self._update_queue_depth_from_progress()
        await self._checkpoint_progress(force=False)

    async def _record_progress_failed(self, *, url: str, error_type: str, error_message: str) -> None:
        if not self._active_progress:
            return
        self._active_progress.mark_url_failed(url=url, error_type=error_type, error_message=error_message)
        self._update_queue_depth_from_progress()
        await self._checkpoint_progress(force=False)

    async def _complete_progress(self) -> None:
        if not self._active_progress:
            return
        self._active_progress.mark_completed()
        await self._checkpoint_progress(force=True, keep_history=True)
        self._active_progress = None
        self.stats.queue_depth = 0

        # Trigger post-sync callback (e.g., rebuild search index)
        if self._on_sync_complete is not None:
            try:
                await self._on_sync_complete()
            except Exception as e:
                logger.error(f"[{self.tenant_codename}] on_sync_complete callback failed: {e}")

    async def _fail_progress(self, reason: str) -> None:
        if not self._active_progress:
            return
        self._active_progress.mark_failed(error=reason)
        await self._checkpoint_progress(force=True, keep_history=True)
        self._active_progress = None

    async def delete_blacklisted_caches(self) -> dict[str, int]:
        """Delete cached documents that match blacklist patterns.

        This method scans all cached documents and deletes any whose URLs
        match the configured blacklist prefixes. Useful for cleaning up
        documents that should no longer be indexed after blacklist rules change.

        Returns:
            Dictionary with deletion statistics:
            - checked: Total documents checked
            - deleted: Number of documents deleted
            - errors: Number of errors encountered
        """
        blacklist = self.settings.get_url_blacklist_prefixes()

        if not blacklist:
            logger.debug("No blacklist configured, skipping cache cleanup")
            return {"checked": 0, "deleted": 0, "errors": 0}

        logger.info(f"Checking cached documents against {len(blacklist)} blacklist patterns")

        stats = {"checked": 0, "deleted": 0, "errors": 0}

        try:
            async with self.uow_factory() as uow:
                # Get all documents (excluding metadata)
                all_docs = await uow.documents.list(limit=100000)

                for doc in all_docs:
                    url = doc.url.value

                    stats["checked"] += 1

                    # Check if URL matches any blacklist pattern
                    if any(url.startswith(prefix) for prefix in blacklist):
                        try:
                            await uow.documents.delete(url)
                            stats["deleted"] += 1
                            logger.info(f"Deleted blacklisted cache: {url}")
                        except Exception as e:
                            logger.error(f"Failed to delete blacklisted cache {url}: {e}")
                            stats["errors"] += 1

                # Commit all deletions
                await uow.commit()

            logger.info(
                f"Blacklist cleanup complete: checked {stats['checked']}, "
                f"deleted {stats['deleted']}, errors {stats['errors']}"
            )

        except Exception as e:
            logger.error(f"Error during blacklist cache cleanup: {e}", exc_info=True)
            stats["errors"] += 1

        return stats

    def get_stats(self) -> dict:
        """Get current scheduler statistics."""
        return asdict(self.stats)
