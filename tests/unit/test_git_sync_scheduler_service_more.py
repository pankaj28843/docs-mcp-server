from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from docs_mcp_server.services.git_sync_scheduler_service import GitSyncSchedulerService
from docs_mcp_server.utils.git_sync import GitSyncResult


class _GitSyncer:
    def __init__(self, result=None, raises: bool = False) -> None:
        self._result = result
        self._raises = raises

    async def sync(self):
        if self._raises:
            raise RuntimeError("boom")
        return self._result


class _MetadataStore:
    def __init__(self) -> None:
        self.saved: list[datetime] = []

    async def save_last_sync_time(self, sync_time: datetime) -> None:
        self.saved.append(sync_time)


@pytest.mark.unit
def test_scheduler_property_returns_self() -> None:
    service = GitSyncSchedulerService(git_syncer=_GitSyncer(), metadata_store=_MetadataStore())

    assert service.scheduler is service


@pytest.mark.unit
def test_stats_calculates_interval_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GitSyncSchedulerService(
        git_syncer=_GitSyncer(),
        metadata_store=_MetadataStore(),
        refresh_schedule="*/5 * * * *",
    )
    service._last_sync_at = datetime.now(timezone.utc)

    class FakeSchedule:
        def __init__(self, next_run: datetime) -> None:
            self._next_run = next_run

        def next(self) -> datetime:
            return self._next_run

    class FakeCron:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def schedule(self, start_date: datetime):
            return FakeSchedule(start_date + timedelta(hours=1))

    monkeypatch.setattr("docs_mcp_server.services.git_sync_scheduler_service.Cron", FakeCron)

    stats = service.stats

    assert stats["schedule_interval_hours"] == pytest.approx(1.0, rel=1e-3)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_status_snapshot_includes_stats() -> None:
    service = GitSyncSchedulerService(git_syncer=_GitSyncer(), metadata_store=_MetadataStore())

    snapshot = await service.get_status_snapshot()

    assert snapshot["scheduler_initialized"] is False
    assert "stats" in snapshot


@pytest.mark.unit
def test_stats_handles_invalid_cron() -> None:
    service = GitSyncSchedulerService(
        git_syncer=_GitSyncer(),
        metadata_store=_MetadataStore(),
        refresh_schedule="bad cron",
    )

    assert service.stats["schedule_interval_hours"] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_returns_error_on_exception() -> None:
    service = GitSyncSchedulerService(git_syncer=_GitSyncer(raises=True), metadata_store=_MetadataStore())

    response = await service.trigger_sync()

    assert response["success"] is False
    assert "Git sync failed" in response["message"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_handles_do_sync_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GitSyncSchedulerService(git_syncer=_GitSyncer(), metadata_store=_MetadataStore())

    async def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "_do_sync", _boom)

    response = await service.trigger_sync()

    assert response["success"] is False
    assert "Git sync error" in response["message"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_do_sync_records_error_on_exception() -> None:
    service = GitSyncSchedulerService(git_syncer=_GitSyncer(raises=True), metadata_store=_MetadataStore())

    result = await service._do_sync()  # pylint: disable=protected-access

    assert result is None
    assert service.stats["errors"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_disabled_returns_false() -> None:
    service = GitSyncSchedulerService(
        git_syncer=_GitSyncer(),
        metadata_store=_MetadataStore(),
        enabled=False,
    )

    assert await service.initialize() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_returns_true_when_already_initialized() -> None:
    service = GitSyncSchedulerService(git_syncer=_GitSyncer(), metadata_store=_MetadataStore())
    service._initialized = True

    assert await service.initialize() is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_scheduler_noops_when_running() -> None:
    service = GitSyncSchedulerService(git_syncer=_GitSyncer(), metadata_store=_MetadataStore())
    service._scheduler_task = asyncio.create_task(asyncio.sleep(0.01))

    service._start_scheduler()  # pylint: disable=protected-access

    assert service._scheduler_task is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_scheduler_returns_without_schedule() -> None:
    service = GitSyncSchedulerService(
        git_syncer=_GitSyncer(),
        metadata_store=_MetadataStore(),
        refresh_schedule=None,
    )

    await service._run_scheduler()  # pylint: disable=protected-access

    assert service.running is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_scheduler_waits_until_next_run(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GitSyncSchedulerService(
        git_syncer=_GitSyncer(),
        metadata_store=_MetadataStore(),
        refresh_schedule="*/5 * * * *",
    )

    class FakeSchedule:
        def __init__(self, next_run: datetime) -> None:
            self._next_run = next_run

        def next(self) -> datetime:
            return self._next_run

    class FakeCron:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def schedule(self, start_date: datetime):
            return FakeSchedule(start_date + timedelta(minutes=1))

    async def fake_wait_for(_awaitable, timeout: float):
        service._stop_event.set()
        return True

    monkeypatch.setattr("docs_mcp_server.services.git_sync_scheduler_service.Cron", FakeCron)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    await service._run_scheduler()  # pylint: disable=protected-access

    assert service.running is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_scheduler_waits_until_next_run_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GitSyncSchedulerService(
        git_syncer=_GitSyncer(),
        metadata_store=_MetadataStore(),
        refresh_schedule="*/5 * * * *",
    )

    class FakeSchedule:
        def __init__(self, next_run: datetime) -> None:
            self._next_run = next_run

        def next(self) -> datetime:
            return self._next_run

    class FakeCron:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def schedule(self, start_date: datetime):
            return FakeSchedule(start_date + timedelta(minutes=1))

    async def fake_wait_for(_awaitable, timeout: float):
        service._stop_event.set()
        raise asyncio.TimeoutError

    monkeypatch.setattr("docs_mcp_server.services.git_sync_scheduler_service.Cron", FakeCron)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    await service._run_scheduler()  # pylint: disable=protected-access

    assert service.running is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_scheduler_success_path_sets_next_sync(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    result = GitSyncResult(
        commit_id="abc123",
        files_copied=2,
        duration_seconds=0.1,
        repo_updated=True,
        export_path=tmp_path,
        warnings=[],
    )

    service = GitSyncSchedulerService(
        git_syncer=_GitSyncer(result=result),
        metadata_store=_MetadataStore(),
        refresh_schedule="*/5 * * * *",
    )

    real_do_sync = service._do_sync

    async def wrapped_do_sync():
        result_value = await real_do_sync()
        service._stop_event.set()
        return result_value

    service._do_sync = wrapped_do_sync  # type: ignore[assignment]

    class FakeSchedule:
        def __init__(self, next_run: datetime) -> None:
            self._next_run = next_run

        def next(self) -> datetime:
            return self._next_run

    class FakeCron:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def schedule(self, start_date: datetime):
            return FakeSchedule(start_date)

    monkeypatch.setattr("docs_mcp_server.services.git_sync_scheduler_service.Cron", FakeCron)

    await service._run_scheduler()  # pylint: disable=protected-access

    assert service._next_sync_at is not None
    assert service._last_result is result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_scheduler_retries_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GitSyncSchedulerService(
        git_syncer=_GitSyncer(result=None),
        metadata_store=_MetadataStore(),
        refresh_schedule="*/5 * * * *",
    )

    class FakeSchedule:
        def __init__(self, next_run: datetime) -> None:
            self._next_run = next_run

        def next(self) -> datetime:
            return self._next_run

    class FakeCron:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def schedule(self, start_date: datetime):
            return FakeSchedule(start_date - timedelta(seconds=1))

    async def fake_wait_for(_awaitable, timeout: float):
        service._stop_event.set()
        raise asyncio.TimeoutError

    monkeypatch.setattr("docs_mcp_server.services.git_sync_scheduler_service.Cron", FakeCron)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    await service._run_scheduler()  # pylint: disable=protected-access

    assert service.running is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_scheduler_breaks_on_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GitSyncSchedulerService(
        git_syncer=_GitSyncer(result=None),
        metadata_store=_MetadataStore(),
        refresh_schedule="*/5 * * * *",
    )

    class FakeSchedule:
        def __init__(self, next_run: datetime) -> None:
            self._next_run = next_run

        def next(self) -> datetime:
            return self._next_run

    class FakeCron:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def schedule(self, start_date: datetime):
            return FakeSchedule(start_date)

    async def fake_wait_for(_awaitable, timeout: float):
        service._stop_event.set()
        return True

    monkeypatch.setattr("docs_mcp_server.services.git_sync_scheduler_service.Cron", FakeCron)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    await service._run_scheduler()  # pylint: disable=protected-access

    assert service.running is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_cancels_scheduler_task() -> None:
    service = GitSyncSchedulerService(git_syncer=_GitSyncer(), metadata_store=_MetadataStore())
    service._scheduler_task = asyncio.create_task(asyncio.sleep(0.01))

    await service.stop()

    assert service.running is False
