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
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import logging
import os
import socket
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from cron_converter import Cron
import httpx
from opentelemetry.trace import SpanKind

from ..config import Settings
from ..domain.sync_progress import SyncProgress
from ..observability.tracing import create_span
from ..utils.crawl_state_store import CrawlStateStore, LockLease
from ..utils.models import SitemapEntry
from ..utils.sync_discovery_runner import SyncDiscoveryRunner
from ..utils.sync_models import (
    SitemapMetadata,
    SyncBatchResult,
    SyncCyclePlan,
    SyncMetadata,
    SyncSchedulerConfig,
    SyncSchedulerStats,
)
from ..utils.sync_scheduler_metadata import SyncSchedulerMetadataMixin
from ..utils.sync_scheduler_progress import SyncSchedulerProgressMixin
from ..utils.sync_sitemap_fetcher import SyncSitemapFetcher


if TYPE_CHECKING:
    from ..service_layer.filesystem_unit_of_work import AbstractUnitOfWork
    from ..services.cache_service import CacheService


logger = logging.getLogger(__name__)
CRAWLER_LOCK_NAME = "crawler"

# Re-export for backward compatibility
__all__ = [
    "SitemapMetadata",
    "SyncBatchResult",
    "SyncCyclePlan",
    "SyncMetadata",
    "SyncScheduler",
    "SyncSchedulerConfig",
    "SyncSchedulerStats",
]


class SyncScheduler(SyncSchedulerProgressMixin, SyncSchedulerMetadataMixin):
    """Orchestrates continuous documentation synchronization with cron-based scheduling."""

    def __init__(
        self,
        settings: Settings,
        uow_factory: "Callable[[], AbstractUnitOfWork]",
        cache_service_factory: "Callable[[], CacheService]",
        metadata_store: CrawlStateStore,
        progress_store: CrawlStateStore,
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
        self._last_maintenance_date: datetime.date | None = None

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
        await self._persist_metadata_summary()
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

        if self._bypass_idempotency and plan.has_previous_metadata:
            try:
                cleared = await self.metadata_store.clear_queue(reason="force_full_sync")
                if cleared:
                    logger.info("Cleared %s queued URLs before force sync", cleared)
                metadata_entries = await self.metadata_store.list_all_metadata()
                known_urls = {entry.get("url") for entry in metadata_entries if entry.get("url")}
                if known_urls:
                    await self.metadata_store.enqueue_urls(
                        known_urls,
                        reason="force_full_sync",
                        force=True,
                        priority=1,
                    )
            except Exception as exc:
                logger.debug("Force sync enqueue skipped: %s", exc)

        if self.mode == "sitemap" and not plan.sitemap_changed and plan.has_previous_metadata:
            if plan.has_documents:
                logger.info("Sitemap unchanged and URLs already tracked with documents, will only check due URLs")
                discovered_urls = set()
            else:
                logger.info("Sitemap unchanged but no documents found - forcing full resync")

        if discovered_urls:
            await self.metadata_store.enqueue_urls(
                discovered_urls,
                reason="sitemap_discovery" if self.mode != "entry" else "entry_discovery",
                force=self._bypass_idempotency,
            )

        if plan.due_urls:
            await self.metadata_store.enqueue_urls(
                plan.due_urls,
                reason="due_refresh",
                force=self._bypass_idempotency,
            )

        self.stats.queue_depth = await self.metadata_store.queue_depth()
        progress.stats = progress.stats.with_updates(
            urls_discovered=progress.stats.urls_discovered + len(discovered_urls),
            urls_pending=self.stats.queue_depth,
        )
        await self._checkpoint_progress(force=True)

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
        total_urls = await self.metadata_store.queue_depth()
        processed = 0
        failed = 0

        async def handle_url(url: str) -> None:
            nonlocal processed, failed
            try:
                await self._process_url(url, plan.sitemap_lastmod_map.get(url))
                processed += 1
                self.stats.urls_processed += 1
                await self._record_progress_processed(url)
            except Exception as exc:
                failed += 1
                self.stats.errors += 1
                await self._mark_url_failed(url, error=exc)

        while True:
            batch = await self.metadata_store.dequeue_batch(self.settings.max_concurrent_requests)
            if not batch:
                break
            await asyncio.gather(*(handle_url(url) for url in batch))
            self.stats.queue_depth = await self.metadata_store.queue_depth()
            progress.stats = progress.stats.with_updates(urls_pending=self.stats.queue_depth)
            await self._checkpoint_progress(force=False)

        return SyncBatchResult(total_urls=total_urls, processed=processed, failed=failed)

    async def _sync_cycle(self, force_crawler: bool = False, force_full_sync: bool = False):
        """Execute one complete synchronization cycle."""
        with create_span(
            "sync.cycle",
            kind=SpanKind.INTERNAL,
            attributes={
                "sync.tenant": self.tenant_codename,
                "sync.force_crawler": force_crawler,
                "sync.force_full": force_full_sync,
            },
        ) as span:
            logger.info("Starting sync cycle (tenant=%s, force_crawler=%s)", self.tenant_codename, force_crawler)
            progress = await self._prepare_progress_for_cycle()

            try:
                plan = await self._build_cycle_plan(force_crawler=force_crawler, force_full_sync=force_full_sync)
                await self._hydrate_queue_from_plan(plan=plan, progress=progress)

                batch_result = await self._run_batch_execution(plan=plan, progress=progress)
                span.set_attribute("sync.processed", batch_result.processed)
                span.set_attribute("sync.failed", batch_result.failed)
                logger.info("Sync cycle complete: processed=%s, failed=%s", batch_result.processed, batch_result.failed)
                await self._complete_progress()
                await self._maybe_run_maintenance()

            except Exception as exc:
                span.set_attribute("error", True)
                logger.error("Sync cycle failed: %s", exc, exc_info=True)
                await self._fail_progress(str(exc))
                raise
            finally:
                self._bypass_idempotency = False
                self.stats.force_full_sync_active = False
                self.stats.schedule_interval_hours_effective = self.schedule_interval_hours

    async def _maybe_run_maintenance(self) -> None:
        today = datetime.now(timezone.utc).date()
        if self._last_maintenance_date == today:
            return
        try:
            await self.metadata_store.maintenance()
            self._last_maintenance_date = today
        except Exception as exc:
            logger.debug("Crawl state maintenance skipped: %s", exc)

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
        fetcher = SyncSitemapFetcher(
            settings=self.settings,
            get_snapshot_callback=self._get_sitemap_snapshot,
            save_snapshot_callback=self._save_sitemap_snapshot,
        )
        return await fetcher.fetch(self.sitemap_urls)

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
        logger.debug("Processing URL: %s", url)
        started_at = datetime.now(timezone.utc)
        url_parts = urlsplit(url)
        with create_span(
            "sync.url.process",
            kind=SpanKind.INTERNAL,
            attributes={
                "sync.tenant": self.tenant_codename,
                "sync.idempotency_bypass": self._bypass_idempotency,
                "sync.sitemap_lastmod_present": sitemap_lastmod is not None,
                "url.host": url_parts.netloc,
                "url.path": url_parts.path,
            },
        ) as span:
            try:
                if not self.settings.should_process_url(url):
                    await self.metadata_store.delete_url_metadata(url, reason="filtered_url")
                    await self.metadata_store.record_event(
                        url=url,
                        event_type="skip_filtered",
                        status="ok",
                        reason="filtered_by_rules",
                    )
                    await self.metadata_store.remove_from_queue(url)
                    self.stats.urls_skipped += 1
                    return
                await self.metadata_store.remove_from_queue(url)
                await self.metadata_store.record_event(
                    url=url,
                    event_type="process_start",
                    status="ok",
                    detail={"bypass_idempotency": self._bypass_idempotency},
                )
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
                                    "Skipping %s - fetched %.1fh ago (interval: %.1fh)",
                                    url,
                                    age_hours,
                                    self.schedule_interval_hours,
                                )
                                span.add_event(
                                    "sync.url.skipped",
                                    {"reason": "recently_fetched", "age_hours": round(age_hours, 2)},
                                )
                                span.set_attribute("sync.skipped", True)
                                self.stats.urls_skipped += 1
                                await self.metadata_store.record_event(
                                    url=url,
                                    event_type="skip_recent",
                                    status="ok",
                                    reason="recently_fetched",
                                    detail={"age_hours": round(age_hours, 2)},
                                )
                                await self._record_progress_skipped(
                                    url,
                                    reason=f"recently_fetched_{age_hours:.1f}h",
                                )
                                return
                    except Exception as e:
                        logger.debug("Could not check metadata for %s: %s", url, e)
                        span.add_event("sync.url.skip_check_failed", {"error.type": e.__class__.__name__})
                elif self._bypass_idempotency:
                    logger.debug("Bypassing idempotency window for %s", url)
                    span.add_event("sync.idempotency.bypass", {})

                cache_service = self.cache_service_factory()
                # Use semantic cache only for non-forced syncs to reduce upstream load.
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
                    markdown_rel_path = None
                    try:
                        async with self.uow_factory() as uow:
                            document = await uow.documents.get(url)
                            if document:
                                markdown_rel_path = document.metadata.markdown_rel_path
                    except Exception:
                        markdown_rel_path = None

                    # Success - reset retry count and update metadata
                    await self._update_metadata(
                        url=url,
                        last_fetched_at=datetime.now(timezone.utc),
                        next_due_at=next_due,
                        status="success",
                        retry_count=0,  # Reset on success
                        markdown_rel_path=markdown_rel_path,
                    )
                    duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
                    await self.metadata_store.record_event(
                        url=url,
                        event_type="cache_hit" if was_cached else "fetch_success",
                        status="ok",
                        detail={
                            "was_cached": was_cached,
                            "markdown_rel_path": markdown_rel_path,
                        },
                        duration_ms=duration_ms,
                    )
                    span.add_event(
                        "sync.url.success",
                        {"cache.hit": was_cached, "next_due_hours": round(self.schedule_interval_hours, 2)},
                    )
                    await self._record_progress_processed(url)
                    return
                # Failed - mark for retry with exponential backoff
                logger.warning("Failed to process %s", url)
                span.add_event("sync.url.failed", {"reason": failure_reason or "PageFetchFailed"})
                duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
                await self.metadata_store.record_event(
                    url=url,
                    event_type="fetch_failure",
                    status="failed",
                    reason=failure_reason or "PageFetchFailed",
                    duration_ms=duration_ms,
                )
                await self._mark_url_failed(url, reason=failure_reason or "PageFetchFailed")

            except Exception as e:
                logger.error("Unhandled error processing %s: %s", url, e, exc_info=True)
                span.add_event("sync.url.error", {"error.type": e.__class__.__name__})
                self.stats.errors += 1
                await self.metadata_store.record_event(
                    url=url,
                    event_type="process_error",
                    status="failed",
                    reason=e.__class__.__name__,
                )
                await self._mark_url_failed(url, error=e)

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
