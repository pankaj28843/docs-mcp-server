"""Git sync scheduler service for git-backed tenants.

Provides periodic sync via cron scheduling, similar to SchedulerService
but using GitRepoSyncer instead of crawler-based SyncScheduler.
"""

import asyncio
from datetime import datetime, timezone
import logging

from cron_converter import Cron

from ..utils.git_sync import GitRepoSyncer, GitSyncResult
from ..utils.sync_metadata_store import SyncMetadataStore


logger = logging.getLogger(__name__)


class GitSyncSchedulerService:
    """Service for managing git-backed documentation synchronization.

    This class provides a scheduler interface similar to SchedulerService
    but uses GitRepoSyncer for git pull/export instead of crawler.
    """

    def __init__(
        self,
        git_syncer: GitRepoSyncer,
        metadata_store: SyncMetadataStore,
        refresh_schedule: str | None = None,
        enabled: bool = True,
    ):
        """Initialize git sync scheduler service.

        Args:
            git_syncer: GitRepoSyncer instance for performing syncs
            metadata_store: Store for sync metadata
            refresh_schedule: Optional cron schedule for automatic refresh
            enabled: Whether scheduler is enabled
        """
        self.git_syncer = git_syncer
        self.metadata_store = metadata_store
        self.refresh_schedule = refresh_schedule
        self.enabled = enabled

        self._initialized = False
        self._running = False
        self._scheduler_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

        # Stats tracking
        self._total_syncs = 0
        self._last_sync_at: datetime | None = None
        self._next_sync_at: datetime | None = None
        self._last_result: GitSyncResult | None = None
        self._errors = 0

    @property
    def is_initialized(self) -> bool:
        """Check if scheduler is initialized and running."""
        return self._initialized

    @property
    def running(self) -> bool:
        """Check if background scheduler is running."""
        return self._running

    @property
    def scheduler(self) -> "GitSyncSchedulerService":
        """Return self for compatibility with SchedulerService interface."""
        return self

    @property
    def stats(self) -> dict:
        """Return lightweight scheduler stats for status endpoints."""
        # Derive an effective interval in hours when a cron is configured; fall back to None.
        interval_hours: float | None = None
        if self.refresh_schedule:
            try:
                cron = Cron(self.refresh_schedule)
                now = datetime.now(timezone.utc)
                next_run = cron.schedule(start_date=self._last_sync_at or now).next()
                interval_hours = (next_run - now).total_seconds() / 3600
            except Exception:
                interval_hours = None

        last_commit = None
        files_copied = None
        if self._last_result:
            last_commit = self._last_result.commit_id
            files_copied = self._last_result.files_copied

        return {
            "mode": "git",
            "refresh_schedule": self.refresh_schedule,
            "schedule_interval_hours": interval_hours,
            "running": self._running,
            "total_syncs": self._total_syncs,
            "last_sync_at": self._last_sync_at.isoformat() if self._last_sync_at else None,
            "next_sync_at": self._next_sync_at.isoformat() if self._next_sync_at else None,
            "errors": self._errors,
            "last_commit_id": last_commit,
            "last_files_copied": files_copied,
        }

    async def get_status_snapshot(self) -> dict:
        """Return scheduler stats for the status endpoint."""
        return self.stats

    async def trigger_sync(self, *, force_crawler: bool = False, force_full_sync: bool = False) -> dict:
        """Trigger a sync manually.

        Args:
            force_crawler: Ignored for git sync (no crawler)
            force_full_sync: Ignored for git sync (always full)

        Returns:
            Dict with success status and message
        """
        try:
            result = await self._do_sync()
            if result:
                return {
                    "success": True,
                    "message": f"Git sync completed: {result.files_copied} files, commit {result.commit_id[:8] if result.commit_id else 'unknown'}",
                    "files_copied": result.files_copied,
                    "commit_id": result.commit_id,
                }
            return {
                "success": False,
                "message": "Git sync failed",
            }
        except Exception as e:
            logger.error(f"Failed to trigger git sync: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Git sync error: {e}",
            }

    async def initialize(self) -> bool:
        """Initialize and start the git sync scheduler.

        Returns:
            True if successful, False otherwise
        """
        if self._initialized:
            logger.debug("Git sync scheduler already initialized")
            return True

        if not self.enabled:
            logger.debug("Git sync scheduler disabled")
            return False

        try:
            logger.info("Initializing git sync scheduler...")

            # Run initial sync
            result = await self._do_sync()
            if result:
                self._initialized = True
                logger.info(f"Initial git sync completed: {result.files_copied} files, commit {result.commit_id[:8]}")
            else:
                logger.warning("Initial git sync failed, will retry")
                return False

            # Start cron scheduler if configured
            if self.refresh_schedule:
                self._start_scheduler()
                logger.info(f"Git sync scheduler started with schedule: {self.refresh_schedule}")
            else:
                logger.info("Git sync scheduler initialized (no cron schedule)")

            return True

        except Exception as e:
            logger.error(f"Failed to initialize git sync scheduler: {e}", exc_info=True)
            return False

    async def _do_sync(self) -> GitSyncResult | None:
        """Perform a git sync operation.

        Returns:
            GitSyncResult on success, None on failure
        """
        try:
            result = await self.git_syncer.sync()
            self._total_syncs += 1
            self._last_sync_at = datetime.now(timezone.utc)
            self._last_result = result

            # Persist last sync time
            await self.metadata_store.save_last_sync_time(self._last_sync_at)

            return result
        except Exception as e:
            self._errors += 1
            logger.error(f"Git sync failed: {e}", exc_info=True)
            return None

    def _start_scheduler(self) -> None:
        """Start the background cron scheduler task."""
        if self._scheduler_task is not None and not self._scheduler_task.done():
            return

        self._running = True
        self._stop_event.clear()
        self._scheduler_task = asyncio.create_task(self._run_scheduler())

    async def _run_scheduler(self) -> None:
        """Background task that runs syncs according to cron schedule."""
        if not self.refresh_schedule:
            return

        # Retry backoff state
        consecutive_failures = 0
        base_retry_delay = 60  # Start with 1 minute delay on failure
        max_retry_delay = 3600  # Cap at 1 hour

        try:
            cron = Cron(self.refresh_schedule)

            while not self._stop_event.is_set():
                # Calculate next sync time from last sync or now
                now = datetime.now(timezone.utc)
                schedule = cron.schedule(start_date=self._last_sync_at or now)
                next_run = schedule.next()
                self._next_sync_at = next_run

                # Check if sync is due (next_run is in the past or now)
                if next_run <= now:
                    # Run sync
                    logger.info("Running scheduled git sync...")
                    result = await self._do_sync()
                    if result:
                        logger.info(
                            f"Scheduled git sync complete: {result.files_copied} files, commit {result.commit_id[:8]}"
                        )
                        consecutive_failures = 0  # Reset on success
                    else:
                        consecutive_failures += 1
                        # Calculate exponential backoff delay
                        retry_delay = min(base_retry_delay * (2 ** (consecutive_failures - 1)), max_retry_delay)
                        logger.warning(
                            f"Scheduled git sync failed (attempt {consecutive_failures}), "
                            f"waiting {retry_delay}s before retry"
                        )
                        # Wait before retrying to avoid tight loop / file descriptor exhaustion
                        try:
                            await asyncio.wait_for(self._stop_event.wait(), timeout=retry_delay)
                            # Stop event was set, exit loop
                            break
                        except asyncio.TimeoutError:
                            # Timeout means we should retry
                            pass
                else:
                    # Wait until next scheduled time (max 60 seconds per check)
                    wait_seconds = min((next_run - now).total_seconds(), 60)
                    if wait_seconds > 0:
                        logger.debug(f"Next git sync in {wait_seconds:.0f}s at {next_run}")
                        try:
                            await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                            # Stop event was set, exit loop
                            break
                        except asyncio.TimeoutError:
                            # Timeout means we should check again
                            pass

        except Exception as e:
            logger.error(f"Git scheduler error: {e}", exc_info=True)
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._stop_event.set()

        # Cancel scheduler task - we intentionally suppress CancelledError
        # since we're the ones cancelling these tasks during cleanup
        if self._scheduler_task is not None and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass  # NOSONAR - intentional suppression during cleanup
            finally:
                self._scheduler_task = None

        self._running = False
        self._initialized = False
