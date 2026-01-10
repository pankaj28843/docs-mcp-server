from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from docs_mcp_server.services.git_sync_scheduler_service import GitSyncSchedulerService


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
def test_stats_handles_invalid_cron() -> None:
    with pytest.raises(ValueError, match="Invalid cron string format"):
        GitSyncSchedulerService(
            git_syncer=_GitSyncer(),
            metadata_store=_MetadataStore(),
            refresh_schedule="bad cron",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_returns_error_on_exception() -> None:
    service = GitSyncSchedulerService(git_syncer=_GitSyncer(raises=True), metadata_store=_MetadataStore())

    response = await service.trigger_sync()

    assert response["success"] is False
    assert "Git sync failed" in response["message"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_do_sync_records_error_on_exception() -> None:
    service = GitSyncSchedulerService(git_syncer=_GitSyncer(raises=True), metadata_store=_MetadataStore())

    await service.trigger_sync()

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

    service._start_scheduler_loop()  # pylint: disable=protected-access

    assert service._scheduler_task is not None


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

    monkeypatch.setattr("docs_mcp_server.services.base_scheduler_service.Cron", FakeCron)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    await service._run_scheduler_loop()  # pylint: disable=protected-access

    assert service.running is False


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

    monkeypatch.setattr("docs_mcp_server.services.base_scheduler_service.Cron", FakeCron)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    await service._run_scheduler_loop()  # pylint: disable=protected-access

    assert service.running is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_cancels_scheduler_task() -> None:
    service = GitSyncSchedulerService(git_syncer=_GitSyncer(), metadata_store=_MetadataStore())
    service._scheduler_task = asyncio.create_task(asyncio.sleep(0.01))

    await service.stop()

    assert service.running is False
