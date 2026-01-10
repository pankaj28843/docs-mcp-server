from __future__ import annotations

from datetime import datetime, timezone

import pytest

from docs_mcp_server.services.git_sync_scheduler_service import GitSyncSchedulerService
from docs_mcp_server.utils.git_sync import GitSyncResult
from docs_mcp_server.utils.sync_metadata_store import SyncMetadataStore


class DummyGitSyncer:
    def __init__(self, result: GitSyncResult | None) -> None:
        self._result = result
        self.calls = 0

    async def sync(self) -> GitSyncResult:
        self.calls += 1
        if self._result is None:
            raise RuntimeError("sync failed")
        return self._result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_reports_success(tmp_path) -> None:
    result = GitSyncResult(
        commit_id="deadbeef",
        files_copied=3,
        duration_seconds=0.1,
        repo_updated=True,
        export_path=tmp_path,
        warnings=[],
    )
    syncer = DummyGitSyncer(result)
    store = SyncMetadataStore(tmp_path)
    service = GitSyncSchedulerService(syncer, store)

    response = await service.trigger_sync()

    assert response["success"] is True
    assert response["files_copied"] == 3
    assert response["commit_id"] == "deadbeef"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_handles_errors(tmp_path) -> None:
    syncer = DummyGitSyncer(None)
    store = SyncMetadataStore(tmp_path)
    service = GitSyncSchedulerService(syncer, store)

    response = await service.trigger_sync()

    assert response["success"] is False
    assert response["message"] == "Git sync failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_respects_disabled_flag(tmp_path) -> None:
    result = GitSyncResult(
        commit_id="deadbeef",
        files_copied=3,
        duration_seconds=0.1,
        repo_updated=True,
        export_path=tmp_path,
        warnings=[],
    )
    syncer = DummyGitSyncer(result)
    store = SyncMetadataStore(tmp_path)
    service = GitSyncSchedulerService(syncer, store, enabled=False)

    initialized = await service.initialize()

    assert initialized is False
    assert service.is_initialized is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_runs_initial_sync(tmp_path) -> None:
    result = GitSyncResult(
        commit_id="deadbeef",
        files_copied=3,
        duration_seconds=0.1,
        repo_updated=True,
        export_path=tmp_path,
        warnings=[],
    )
    syncer = DummyGitSyncer(result)
    store = SyncMetadataStore(tmp_path)
    service = GitSyncSchedulerService(syncer, store, refresh_schedule=None)

    initialized = await service.initialize()

    assert initialized is True
    assert service.is_initialized is True
    assert service.running is False
    assert syncer.calls == 1


@pytest.mark.unit
def test_stats_reports_last_result(tmp_path) -> None:
    result = GitSyncResult(
        commit_id="deadbeef",
        files_copied=3,
        duration_seconds=0.1,
        repo_updated=True,
        export_path=tmp_path,
        warnings=[],
    )
    syncer = DummyGitSyncer(result)
    store = SyncMetadataStore(tmp_path)
    service = GitSyncSchedulerService(syncer, store)

    service._last_result_obj = result  # pylint: disable=protected-access
    service._last_sync_at = datetime.now(timezone.utc)

    stats = service.stats

    assert stats["last_commit_id"] == "deadbeef"
    assert stats["last_files_copied"] == 3
