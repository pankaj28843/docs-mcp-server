"""Unit tests for GitSyncSchedulerService behavior."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from docs_mcp_server.services.git_sync_scheduler_service import GitSyncSchedulerService
from docs_mcp_server.utils.git_sync import GitSyncResult


@pytest.fixture
def git_result(tmp_path: Path) -> GitSyncResult:
    return GitSyncResult(
        commit_id="abcdef123456",
        files_copied=42,
        duration_seconds=1.2,
        repo_updated=True,
        export_path=tmp_path,
        warnings=["minor"],
    )


@pytest.fixture
def git_syncer(git_result: GitSyncResult) -> SimpleNamespace:
    return SimpleNamespace(sync=AsyncMock(return_value=git_result))


@pytest.fixture
def metadata_store() -> SimpleNamespace:
    return SimpleNamespace(save_last_sync_time=AsyncMock())


@pytest.fixture
def service(git_syncer: SimpleNamespace, metadata_store: SimpleNamespace) -> GitSyncSchedulerService:
    return GitSyncSchedulerService(git_syncer=git_syncer, metadata_store=metadata_store)


@pytest.mark.unit
class TestGitSyncSchedulerService:
    """Covers sync bookkeeping, status reporting, and scheduling helpers."""

    @pytest.mark.asyncio
    async def test_do_sync_updates_counters(
        self,
        service: GitSyncSchedulerService,
        git_result: GitSyncResult,
        metadata_store: SimpleNamespace,
    ) -> None:
        result = await service._execute_and_record(  # pylint: disable=protected-access
            force_crawler=False,
            force_full_sync=False,
        )

        assert result["success"] is True
        assert result["commit_id"] == git_result.commit_id
        assert service._total_syncs == 1  # pylint: disable=protected-access
        assert service._last_result_obj is git_result  # pylint: disable=protected-access
        metadata_store.save_last_sync_time.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_do_sync_handles_exceptions(
        self, service: GitSyncSchedulerService, git_syncer: SimpleNamespace
    ) -> None:
        git_syncer.sync.side_effect = RuntimeError("boom")

        result = await service._execute_and_record(  # pylint: disable=protected-access
            force_crawler=False,
            force_full_sync=False,
        )

        assert result["success"] is False
        assert service._errors == 1  # pylint: disable=protected-access

    @pytest.mark.asyncio
    async def test_initialize_respects_disabled_flag(
        self,
        git_syncer: SimpleNamespace,
        metadata_store: SimpleNamespace,
    ) -> None:
        scheduler = GitSyncSchedulerService(git_syncer=git_syncer, metadata_store=metadata_store, enabled=False)

        assert await scheduler.initialize() is False

    @pytest.mark.asyncio
    async def test_initialize_starts_scheduler_when_schedule_set(
        self,
        git_syncer: SimpleNamespace,
        metadata_store: SimpleNamespace,
        git_result: GitSyncResult,
    ) -> None:
        scheduler = GitSyncSchedulerService(
            git_syncer=git_syncer,
            metadata_store=metadata_store,
            refresh_schedule="*/5 * * * *",
        )
        scheduler._do_sync = AsyncMock(return_value=git_result)  # type: ignore[attr-defined]
        scheduler._start_scheduler_loop = MagicMock()  # type: ignore[attr-defined]

        assert await scheduler.initialize() is True
        scheduler._start_scheduler_loop.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_initialize_returns_false_when_initial_sync_fails(
        self,
        git_syncer: SimpleNamespace,
        metadata_store: SimpleNamespace,
    ) -> None:
        scheduler = GitSyncSchedulerService(git_syncer=git_syncer, metadata_store=metadata_store)
        scheduler._do_sync = AsyncMock(return_value=None)  # type: ignore[attr-defined]

        assert await scheduler.initialize() is False

    @pytest.mark.asyncio
    async def test_initialize_handles_do_sync_exceptions(
        self,
        git_syncer: SimpleNamespace,
        metadata_store: SimpleNamespace,
    ) -> None:
        scheduler = GitSyncSchedulerService(git_syncer=git_syncer, metadata_store=metadata_store)
        scheduler._do_sync = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[attr-defined]

        assert await scheduler.initialize() is False
        assert scheduler._initialized is False  # pylint: disable=protected-access

    def test_is_initialized_and_running_reflect_flags(self, service: GitSyncSchedulerService) -> None:
        service._initialized = True  # pylint: disable=protected-access
        service._running = True  # pylint: disable=protected-access

        assert service.is_initialized is True
        assert service.running is True

        service._running = False  # pylint: disable=protected-access
        assert service.is_initialized is True
        assert service.running is False

        service._initialized = False  # pylint: disable=protected-access
        assert service.is_initialized is False

    @pytest.mark.asyncio
    async def test_initialize_returns_true_when_already_initialized(self, service: GitSyncSchedulerService) -> None:
        service._initialized = True  # pylint: disable=protected-access
        service._running = True  # pylint: disable=protected-access

        assert await service.initialize() is True

    @pytest.mark.asyncio
    async def test_initialize_without_schedule_idles_scheduler(
        self,
        git_syncer: SimpleNamespace,
        metadata_store: SimpleNamespace,
        git_result: GitSyncResult,
    ) -> None:
        scheduler = GitSyncSchedulerService(git_syncer=git_syncer, metadata_store=metadata_store)
        scheduler._do_sync = AsyncMock(return_value=git_result)  # type: ignore[attr-defined]
        scheduler._start_scheduler_loop = MagicMock()  # type: ignore[attr-defined]

        result = await scheduler.initialize()

        assert result is True
        scheduler._start_scheduler_loop.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_scheduler_applies_backoff_after_failure(
        self,
        git_syncer: SimpleNamespace,
        metadata_store: SimpleNamespace,
        git_result: GitSyncResult,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _DeterministicCron:
            def __init__(self, *_args, **_kwargs):
                self._start_date = None

            def schedule(self, *_args, start_date=None, **_kwargs):
                self._start_date = start_date
                return self

            def next(self):
                return self._start_date or datetime.now(timezone.utc)

        monkeypatch.setattr("docs_mcp_server.services.base_scheduler_service.Cron", _DeterministicCron)


        service = GitSyncSchedulerService(
            git_syncer=git_syncer,
            metadata_store=metadata_store,
            refresh_schedule="* * * * *",
        )

        async def fake_sync():
            raise RuntimeError("boom")

        git_syncer.sync.side_effect = fake_sync

        wait_calls: list[float] = []
        real_wait_for = asyncio.wait_for

        async def fake_wait_for(awaitable, timeout):
            if timeout >= 60 and not service._stop_event.is_set():
                wait_calls.append(timeout)
                service._stop_event.set()  # pylint: disable=protected-access
                raise asyncio.TimeoutError
            return await real_wait_for(awaitable, timeout=timeout)

        monkeypatch.setattr("docs_mcp_server.services.base_scheduler_service.asyncio.wait_for", fake_wait_for)

        await service._run_scheduler_loop()  # pylint: disable=protected-access

        assert 60 in wait_calls
        assert service._errors == 1  # pylint: disable=protected-access
        assert service._total_syncs == 0  # pylint: disable=protected-access
        assert service._next_sync_at is not None  # pylint: disable=protected-access
        metadata_store.save_last_sync_time.assert_not_awaited()
        assert git_syncer.sync.await_count == 1

    def test_start_scheduler_loop_skips_when_task_active(
        self,
        git_syncer: SimpleNamespace,
        metadata_store: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        scheduler = GitSyncSchedulerService(
            git_syncer=git_syncer, metadata_store=metadata_store, refresh_schedule="*/5 * * * *"
        )
        existing_task = MagicMock()
        existing_task.done.return_value = False
        scheduler._scheduler_task = existing_task  # pylint: disable=protected-access

        created: list[str] = []

        def fake_create_task(_):
            created.append("created")
            return AsyncMock()

        monkeypatch.setattr(
            "docs_mcp_server.services.base_scheduler_service.asyncio.create_task",
            fake_create_task,
        )

        scheduler._start_scheduler_loop()

        assert created == []

    @pytest.mark.asyncio
    async def test_stop_cancels_background_tasks(
        self,
        git_syncer: SimpleNamespace,
        metadata_store: SimpleNamespace,
    ) -> None:
        scheduler = GitSyncSchedulerService(
            git_syncer=git_syncer,
            metadata_store=metadata_store,
            refresh_schedule="*/10 * * * *",
        )
        scheduler._scheduler_task = asyncio.create_task(asyncio.sleep(60))  # pylint: disable=protected-access
        scheduler._running = True  # pylint: disable=protected-access
        scheduler._initialized = True  # pylint: disable=protected-access

        await scheduler.stop()

        assert scheduler._scheduler_task is None  # pylint: disable=protected-access
        assert scheduler._running is False  # pylint: disable=protected-access
        assert scheduler._initialized is False  # pylint: disable=protected-access

    def test_start_scheduler_loop_creates_task_when_idle(
        self,
        git_syncer: SimpleNamespace,
        metadata_store: SimpleNamespace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        scheduler = GitSyncSchedulerService(
            git_syncer=git_syncer,
            metadata_store=metadata_store,
            refresh_schedule="*/15 * * * *",
        )

        created: list[asyncio.Task] = []

        task = MagicMock()
        task.done.return_value = True

        def fake_create_task(coro):
            created.append(coro)
            return task

        monkeypatch.setattr(
            "docs_mcp_server.services.base_scheduler_service.asyncio.create_task",
            fake_create_task,
        )

        scheduler._start_scheduler_loop()

        assert scheduler._running is True
        assert scheduler._scheduler_task is task
        assert created, "Expected asyncio.create_task to be invoked"

    @pytest.mark.asyncio
    async def test_run_scheduler_handles_cron_errors(
        self, metadata_store: SimpleNamespace, git_syncer: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = GitSyncSchedulerService(
            git_syncer=git_syncer,
            metadata_store=metadata_store,
            refresh_schedule="0 * * * *",
        )

        class BrokenCron:
            def schedule(self, *_args, **_kwargs):
                raise RuntimeError("cron fail")

        service._cron = BrokenCron()  # pylint: disable=protected-access

        await service._run_scheduler_loop()

        assert service._running is False

    def test_stats_include_running_flag(self, service: GitSyncSchedulerService) -> None:
        stats = service.stats
        assert stats["running"] is False

        service._running = True  # pylint: disable=protected-access
        stats = service.stats
        assert stats["running"] is True
