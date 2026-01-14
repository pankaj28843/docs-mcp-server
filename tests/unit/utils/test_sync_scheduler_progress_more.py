"""Additional unit tests for SyncSchedulerProgressMixin."""

from datetime import timedelta

import pytest

from docs_mcp_server.domain.sync_progress import SyncProgress
from docs_mcp_server.utils.sync_scheduler_progress import SyncSchedulerProgressMixin


class _DummyProgressStore:
    def __init__(self) -> None:
        self.saved = 0
        self.checkpoints = 0

    async def get_latest_for_tenant(self, _tenant: str):
        return None

    async def save(self, _progress: SyncProgress) -> None:
        self.saved += 1

    async def save_checkpoint(self, *_args, **_kwargs) -> None:
        self.checkpoints += 1


class _DummyStats:
    queue_depth = 0


class _DummyScheduler(SyncSchedulerProgressMixin):
    def __init__(self) -> None:
        self._active_progress = None
        self._last_progress_checkpoint = None
        self._checkpoint_interval = timedelta(seconds=1)
        self.progress_store = _DummyProgressStore()
        self.tenant_codename = "tenant"
        self.stats = _DummyStats()
        self._on_sync_complete = None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_or_create_progress_returns_existing():
    scheduler = _DummyScheduler()
    scheduler._active_progress = SyncProgress.create_new("tenant")

    progress = await scheduler._load_or_create_progress()

    assert progress is scheduler._active_progress


@pytest.mark.unit
@pytest.mark.asyncio
async def test_checkpoint_progress_no_active_progress_is_noop():
    scheduler = _DummyScheduler()

    await scheduler._checkpoint_progress(force=True)

    assert scheduler.progress_store.saved == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_progress_logs_callback_error(caplog):
    scheduler = _DummyScheduler()
    scheduler._active_progress = SyncProgress.create_new("tenant")

    async def _boom():
        raise RuntimeError("boom")

    scheduler._on_sync_complete = _boom

    await scheduler._complete_progress()

    assert scheduler._active_progress is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fail_progress_marks_failed_and_clears_active():
    scheduler = _DummyScheduler()
    scheduler._active_progress = SyncProgress.create_new("tenant")

    await scheduler._fail_progress("failure")

    assert scheduler._active_progress is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_progress_no_active_is_noop():
    scheduler = _DummyScheduler()

    await scheduler._complete_progress()

    assert scheduler.stats.queue_depth == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fail_progress_no_active_is_noop():
    scheduler = _DummyScheduler()

    await scheduler._fail_progress("failure")

    assert scheduler._active_progress is None
