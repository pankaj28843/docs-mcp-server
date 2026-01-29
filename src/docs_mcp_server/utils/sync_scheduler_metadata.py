"""Metadata and stats helpers for sync scheduler."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import TYPE_CHECKING, Any

from .sync_models import SitemapMetadata, SyncMetadata


if TYPE_CHECKING:
    from ..services.cache_service import CacheService

logger = logging.getLogger(__name__)

SITEMAP_SNAPSHOT_ID = "current_sitemap"


class SyncSchedulerMetadataMixin:
    """Mix-in for sync metadata, stats, and persistence helpers."""

    def _calculate_next_due(self, sitemap_lastmod: datetime | None = None) -> datetime:
        """Calculate next sync due date based on sitemap lastmod."""
        now = datetime.now(timezone.utc)

        if sitemap_lastmod:
            if sitemap_lastmod.tzinfo is None:
                sitemap_lastmod = sitemap_lastmod.replace(tzinfo=timezone.utc)

            days_since_mod = (now - sitemap_lastmod).days

            if days_since_mod < 7:
                return now + timedelta(days=1)
            if days_since_mod < 30:
                return now + timedelta(days=self.settings.default_sync_interval_days)
            return now + timedelta(days=self.settings.max_sync_interval_days)

        return now + timedelta(days=self.settings.default_sync_interval_days)

    async def _update_metadata(
        self,
        url: str,
        last_fetched_at: datetime,
        next_due_at: datetime,
        status: str,
        retry_count: int,
        markdown_rel_path: str | None = None,
    ) -> None:
        """Update metadata for a URL."""
        existing_payload = await self.metadata_store.load_url_metadata(url)
        existing = SyncMetadata.from_dict(existing_payload) if existing_payload else SyncMetadata(url=url)

        existing.last_fetched_at = last_fetched_at
        existing.next_due_at = next_due_at
        existing.last_status = status
        existing.retry_count = retry_count
        if markdown_rel_path:
            existing.markdown_rel_path = markdown_rel_path
        if status == "success":
            existing.last_failure_reason = None
            existing.last_failure_at = None

        await self.metadata_store.upsert_url_metadata(existing.to_dict())

    async def _mark_url_failed(self, url: str, *, error: Exception | None = None, reason: str | None = None) -> None:
        """Mark URL as failed and schedule retry with backoff."""
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

        await self.metadata_store.upsert_url_metadata(metadata.to_dict())

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
            self.stats.metadata_snapshot_path = f"crawl_debug:{snapshot_name}"
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

    async def _persist_metadata_summary(self) -> None:
        payload = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "total": self.stats.metadata_total_urls,
            "due": self.stats.metadata_due_urls,
            "successful": self.stats.metadata_successful,
            "pending": self.stats.metadata_pending,
            "first_seen_at": self.stats.metadata_first_seen_at,
            "last_success_at": self.stats.metadata_last_success_at,
            "failed_count": self.stats.failed_url_count,
            "metadata_sample": self.stats.metadata_sample,
            "failure_sample": self.stats.failure_sample,
            "storage_doc_count": self.stats.storage_doc_count,
        }
        await self.metadata_store.save_summary(payload)

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

    async def _load_sitemap_metadata(self) -> None:
        """Load sitemap metadata from storage."""
        try:
            snapshot = await self._get_sitemap_snapshot()
            if snapshot:
                self.sitemap_metadata = SitemapMetadata.from_snapshot(snapshot)
                self.stats.sitemap_total_urls = self.sitemap_metadata.total_urls
                logger.info("Loaded sitemap metadata: %s URLs", self.sitemap_metadata.total_urls)
            else:
                self.sitemap_metadata = SitemapMetadata()
                logger.debug("No sitemap metadata found yet")
        except Exception as exc:
            logger.debug("Could not load sitemap metadata: %s", exc)

    async def _update_cache_stats(self) -> None:
        """Query storage to get actual cached document count."""
        try:
            async with self.uow_factory() as uow:
                cache_count = await uow.documents.count()
                self.stats.storage_doc_count = cache_count

                sitemap_count = self.sitemap_metadata.total_urls
                if sitemap_count > 0:
                    cache_pct = (cache_count / sitemap_count) * 100
                    logger.info("Filesystem storage: %s/%s URLs (%.1f%%)", cache_count, sitemap_count, cache_pct)
                else:
                    logger.info("Filesystem storage: %s URLs", cache_count)
        except Exception as exc:
            logger.debug("Could not query cache count: %s", exc)

    def _refresh_fetcher_metrics(self, cache_service: CacheService | None = None) -> None:
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

    async def _ensure_metadata_can_be_accessed(self) -> None:
        """Ensure metadata can be accessed by doing a simple count."""
        try:
            async with self.uow_factory() as uow:
                await uow.documents.count()
            self.metadata_store.ensure_ready()
            await self.metadata_store.cleanup_legacy_artifacts()
            logger.info("Metadata storage is accessible.")
        except Exception as exc:
            logger.error("Failed to access metadata storage: %s", exc, exc_info=True)
            raise

    async def _get_sitemap_snapshot(self, snapshot_id: str = SITEMAP_SNAPSHOT_ID) -> dict | None:
        """Get the current sitemap snapshot."""
        try:
            return await self.metadata_store.get_sitemap_snapshot(snapshot_id)
        except Exception as err:
            logger.debug("Could not load sitemap snapshot %s: %s", snapshot_id, err)
            return None

    async def _save_sitemap_snapshot(self, snapshot: dict, snapshot_id: str = SITEMAP_SNAPSHOT_ID) -> None:
        """Save sitemap snapshot."""
        try:
            await self.metadata_store.save_sitemap_snapshot(snapshot, snapshot_id)
        except Exception as err:
            logger.debug("Failed to persist sitemap snapshot %s: %s", snapshot_id, err)
