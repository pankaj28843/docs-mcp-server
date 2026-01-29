"""Progress tracking helpers for sync scheduler."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from ..domain.sync_progress import SyncPhase, SyncProgress


logger = logging.getLogger(__name__)


class SyncSchedulerProgressMixin:
    """Mix-in for sync progress checkpointing and lifecycle updates."""

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

    async def _update_queue_depth_from_progress(self) -> None:
        if hasattr(self, "metadata_store"):
            try:
                self.stats.queue_depth = await self.metadata_store.queue_depth()
                if self._active_progress:
                    self._active_progress.stats = self._active_progress.stats.with_updates(
                        urls_pending=self.stats.queue_depth
                    )
                return
            except Exception:
                pass
        if self._active_progress:
            # Fallback to in-memory progress state when metadata_store is unavailable.
            # pending_urls is an in-memory collection, so len() is synchronous.
            self.stats.queue_depth = len(self._active_progress.pending_urls)

    async def _record_progress_processed(self, url: str) -> None:
        if not self._active_progress:
            return
        self._active_progress.mark_url_processed(url)
        await self._update_queue_depth_from_progress()
        await self._checkpoint_progress(force=False)

    async def _record_progress_skipped(self, url: str, reason: str) -> None:
        if not self._active_progress:
            return
        self._active_progress.mark_url_skipped(url, reason)
        await self._update_queue_depth_from_progress()
        await self._checkpoint_progress(force=False)

    async def _record_progress_failed(self, *, url: str, error_type: str, error_message: str) -> None:
        if not self._active_progress:
            return
        self._active_progress.mark_url_failed(url=url, error_type=error_type, error_message=error_message)
        await self._update_queue_depth_from_progress()
        await self._checkpoint_progress(force=False)

    async def _complete_progress(self) -> None:
        if not self._active_progress:
            return
        self._active_progress.mark_completed()
        await self._checkpoint_progress(force=True, keep_history=True)
        self._active_progress = None
        self.stats.queue_depth = 0

        if self._on_sync_complete is not None:
            try:
                await self._on_sync_complete()
            except Exception as exc:
                logger.error("[%s] on_sync_complete callback failed: %s", self.tenant_codename, exc)

    async def _fail_progress(self, reason: str) -> None:
        if not self._active_progress:
            return
        self._active_progress.mark_failed(error=reason)
        await self._checkpoint_progress(force=True, keep_history=True)
        self._active_progress = None
