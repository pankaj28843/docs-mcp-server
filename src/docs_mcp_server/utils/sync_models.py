"""Data models for sync scheduler operations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from docs_mcp_server.domain.sync_progress import SyncProgress


@dataclass(slots=True)
class SyncSchedulerConfig:
    """Configuration payload for SyncScheduler."""

    sitemap_urls: list[str] | None = None
    entry_urls: list[str] | None = None
    refresh_schedule: str | None = None


class SyncMetadata:
    """Metadata for tracking URL synchronization state."""

    def __init__(  # noqa: PLR0913
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
    def from_dict(cls, data: dict) -> SyncMetadata:
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
    """Statistics and state tracking for sync scheduler operations."""

    mode: str = ""
    refresh_schedule: str | None = None
    schedule_interval_hours: float = 24.0
    schedule_interval_hours_effective: float = 24.0
    total_syncs: int = 0
    last_sync_at: str | None = None
    next_sync_at: str | None = None
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
    sitemap_total_urls: int = 0
    storage_doc_count: int = 0
    last_crawler_run: str | None = None
    crawler_total_runs: int = 0
    crawler_lock_status: str = "unlocked"
    crawler_lock_owner: str | None = None
    crawler_lock_expires_at: str | None = None
    discovery_root_urls: int = 0
    discovery_discovered: int = 0
    discovery_filtered: int = 0
    discovery_progressively_processed: int = 0
    discovery_sample: list[str] = field(default_factory=list)
    metadata_total_urls: int = 0
    metadata_due_urls: int = 0
    metadata_successful: int = 0
    metadata_pending: int = 0
    metadata_first_seen_at: str | None = None
    metadata_last_success_at: str | None = None
    metadata_snapshot_path: str | None = None
    metadata_sample: list[str] = field(default_factory=list)
    force_full_sync_active: bool = False
    failed_url_count: int = 0
    failure_sample: list[str] = field(default_factory=list)
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
    def from_snapshot(cls, snapshot: dict[str, Any]) -> SitemapMetadata:
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


# Type aliases for batch processing callbacks
BatchProcessor = Callable[[str, str | None], Coroutine[Any, Any, None]]
CheckpointHook = Callable[[bool], Coroutine[Any, Any, None]]
FailureHook = Callable[[str, Exception], Coroutine[Any, Any, None]]
SleepHook = Callable[[float], Coroutine[Any, Any, None]]


@dataclass(slots=True)
class SyncBatchRunner:
    """Encapsulates batch execution for sync cycles with backpressure."""

    plan: SyncCyclePlan
    queue: list[str]
    batch_size: int
    process_url: BatchProcessor
    checkpoint: CheckpointHook
    on_failure: FailureHook
    sleep: SleepHook
    progress: SyncProgress
    on_success: Callable[[], None] | None = None
    on_error: Callable[[], None] | None = None

    async def run(self) -> SyncBatchResult:
        """Execute batch processing with queue-based backpressure."""
        self.progress.start_fetching()
        await self.checkpoint(True)

        pending_urls = list(self.progress.pending_urls)
        if not pending_urls:
            return SyncBatchResult(total_urls=0, processed=0, failed=0)

        batch_size = max(1, self.batch_size)
        total_urls = len(pending_urls)
        processed = 0
        failed = 0
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=batch_size * 2)

        async def worker() -> None:
            nonlocal processed, failed
            while True:
                url = await queue.get()
                try:
                    if url is None:
                        return
                    await self.process_url(url, self.plan.sitemap_lastmod_map.get(url))
                    if self.on_success:
                        self.on_success()
                    processed += 1
                except Exception as exc:
                    if self.on_error:
                        try:
                            self.on_error()
                        except Exception:
                            pass
                    try:
                        await self.on_failure(url, exc)
                    except Exception:
                        pass
                    failed += 1
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(batch_size)]
        for url in pending_urls:
            await queue.put(url)
        for _ in range(batch_size):
            await queue.put(None)

        await queue.join()
        await asyncio.gather(*workers)
        await self.checkpoint(False)

        return SyncBatchResult(total_urls=total_urls, processed=processed, failed=failed)
