"""Git sync scheduler service powered by the shared lifecycle base."""

from datetime import datetime, timezone
import logging
from typing import Any

from ..utils.git_sync import GitRepoSyncer, GitSyncResult
from ..utils.sync_metadata_store import SyncMetadataStore
from .base_scheduler_service import BaseSchedulerService


logger = logging.getLogger(__name__)


class GitSyncSchedulerService(BaseSchedulerService):
    """Service for managing git-backed documentation synchronization."""

    def __init__(
        self,
        git_syncer: GitRepoSyncer,
        metadata_store: SyncMetadataStore,
        refresh_schedule: str | None = None,
        enabled: bool = True,
    ):
        super().__init__(
            mode="git",
            refresh_schedule=refresh_schedule,
            enabled=enabled,
            run_triggers_in_background=False,
            manage_cron_loop=True,
            allow_triggers_before_init=True,
        )
        self.git_syncer = git_syncer
        self.metadata_store = metadata_store
        self._last_result_obj: GitSyncResult | None = None

    async def _initialize_impl(self) -> bool:
        result = await self._execute_and_record(force_crawler=False, force_full_sync=True)
        if not result.get("success"):
            logger.warning("Initial git sync failed, scheduler will retry on next trigger")
            return False
        return True

    async def _stop_impl(self) -> None:  # pragma: no cover - nothing extra to close
        return None

    async def _execute_sync_impl(self, *, force_crawler: bool, force_full_sync: bool) -> dict:
        sync_result = await self._do_sync()
        if sync_result is None:
            return {
                "success": False,
                "message": "Git sync failed",
            }

        commit_display = (
            sync_result.commit_id[:8] if sync_result.commit_id and len(sync_result.commit_id) >= 8 else "unknown"
        )
        return {
            "success": True,
            "message": f"Git sync completed: {sync_result.files_copied} files, commit {commit_display}",
            "files_copied": sync_result.files_copied,
            "commit_id": sync_result.commit_id,
        }

    async def _do_sync(self) -> GitSyncResult | None:
        try:
            result = await self.git_syncer.sync()
        except Exception as exc:
            logger.error("Git sync failed: %s", exc, exc_info=True)
            return None

        self._last_result_obj = result
        completed_at = datetime.now(timezone.utc)
        await self.metadata_store.save_last_sync_time(completed_at)
        return result

    def _extra_stats(self) -> dict[str, object]:
        interval_hours = self._schedule_interval_hours()
        last_commit = None
        files_copied = None
        if self._last_result_obj:
            last_commit = self._last_result_obj.commit_id
            files_copied = self._last_result_obj.files_copied

        return {
            "schedule_interval_hours": interval_hours,
            "running": self.running,
            "last_commit_id": last_commit,
            "last_files_copied": files_copied,
        }

    def _result_payload_from_sync_result(self, result: dict[str, Any]) -> dict[str, Any] | None:
        return {
            "files_copied": result.get("files_copied"),
            "commit_id": result.get("commit_id"),
        }
