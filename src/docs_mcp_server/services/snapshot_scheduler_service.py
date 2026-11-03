"""Scheduled refresh of managed, latest-stable filesystem snapshots."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path

from cron_converter import Cron

from ..snapshots import rxjs_api
from ..utils.crawl_state_store import CrawlStateStore


logger = logging.getLogger(__name__)


class SnapshotSchedulerService:
    """Refresh a snapshot and publish its search index as one reported operation."""

    def __init__(
        self,
        source: str,
        root: Path,
        metadata_store: CrawlStateStore,
        refresh_schedule: str | None,
        enabled: bool,
        on_sync_complete: Callable[[], Awaitable[None]],
    ):
        self.source = source
        self.root = root
        self.metadata_store = metadata_store
        self.refresh_schedule = refresh_schedule
        self.enabled = enabled
        self._on_sync_complete = on_sync_complete
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._initialized = False
        self._last_sync_at: datetime | None = None
        self._next_sync_at: datetime | None = None
        self._last_error: str | None = None
        self._total_syncs = 0
        self._errors = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def scheduler(self):
        return self

    @property
    def stats(self) -> dict:
        return {
            "mode": "snapshot",
            "source": self.source,
            "running": self.running,
            "refresh_schedule": self.refresh_schedule,
            "total_syncs": self._total_syncs,
            "last_sync_at": self._last_sync_at.isoformat() if self._last_sync_at else None,
            "next_sync_at": self._next_sync_at.isoformat() if self._next_sync_at else None,
            "errors": self._errors,
            "last_error": self._last_error,
        }

    async def get_status_snapshot(self) -> dict:
        return {"scheduler_running": self.running, "scheduler_initialized": self.is_initialized, "stats": self.stats}

    async def trigger_sync(self, *, force_crawler: bool = False, force_full_sync: bool = False) -> dict:
        async with self._lock:
            try:
                await rxjs_api.export_snapshot(self.root / "snapshot")
                await self._on_sync_complete()
                now = datetime.now(timezone.utc)
                self.metadata_store.ensure_ready()
                await self.metadata_store.save_last_sync_time(now)
                self._last_sync_at = now
                self._last_error = None
                self._total_syncs += 1
                return {"success": True, "message": "Snapshot refreshed and indexed"}
            except Exception as exc:
                self._errors += 1
                self._last_error = str(exc)
                logger.exception("Snapshot refresh failed for %s", self.source)
                return {"success": False, "message": f"Snapshot refresh failed: {exc}"}

    async def initialize(self) -> bool:
        if self._initialized:
            return True
        if not self.enabled:
            return False
        result = await self.trigger_sync()
        self._initialized = True
        if self.refresh_schedule:
            self._task = asyncio.create_task(self._run(not result["success"]))
        return result["success"]

    async def _run(self, retry: bool) -> None:
        cron = Cron(self.refresh_schedule)
        while True:
            now = datetime.now(timezone.utc)
            self._next_sync_at = now + timedelta(seconds=60) if retry else cron.schedule(start_date=now).next()
            delay = max(0, (self._next_sync_at - now).total_seconds())
            await asyncio.sleep(delay)
            result = await self.trigger_sync()
            retry = not result["success"]

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._initialized = False
        self._next_sync_at = None
