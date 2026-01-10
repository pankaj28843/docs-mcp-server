from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.services.scheduler_service import SchedulerService, SchedulerServiceConfig
from docs_mcp_server.utils.sync_metadata_store import SyncMetadataStore
from docs_mcp_server.utils.sync_progress_store import SyncProgressStore


class _DummyDocuments:
    def __init__(self, count: int) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class _DummyUoW:
    def __init__(self, count: int) -> None:
        self.documents = _DummyDocuments(count)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _build_service(tmp_path, *, enabled: bool = True, urls: list[str] | None = None) -> SchedulerService:
    resolved_urls = urls if urls is not None else ["https://example.com"]
    settings = Settings(docs_name="Docs", docs_entry_url=resolved_urls)
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    def uow_factory() -> _DummyUoW:
        return _DummyUoW(3)

    return SchedulerService(
        settings=settings,
        uow_factory=uow_factory,
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SchedulerServiceConfig(entry_urls=resolved_urls, enabled=enabled),
    )


@pytest.mark.unit
def test_stats_returns_empty_without_scheduler(tmp_path) -> None:
    service = _build_service(tmp_path)

    stats = service.stats
    assert stats["mode"] == "crawler"
    assert stats["total_syncs"] == 0
    assert stats["errors"] == 0


@pytest.mark.unit
def test_stats_returns_dict_from_scheduler(tmp_path) -> None:
    service = _build_service(tmp_path)
    service._scheduler = SimpleNamespace(stats={"ok": True})

    stats = service.stats
    assert stats["ok"] is True
    assert stats["mode"] == "crawler"


@pytest.mark.unit
def test_stats_returns_empty_for_non_dict(tmp_path) -> None:
    service = _build_service(tmp_path)
    service._scheduler = SimpleNamespace(stats=["bad"])

    stats = service.stats
    assert stats["mode"] == "crawler"
    assert stats["total_syncs"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_status_snapshot_uses_scheduler_stats(tmp_path) -> None:
    service = _build_service(tmp_path)
    service._scheduler = SimpleNamespace(stats={"queue_depth": 2})
    service._initialized = True  # pylint: disable=protected-access

    snapshot = await service.get_status_snapshot()

    assert snapshot["scheduler_initialized"] is True
    assert snapshot["scheduler_running"] is False
    assert snapshot["stats"] == {"queue_depth": 2}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_status_snapshot_builds_fallback_when_uninitialized(tmp_path) -> None:
    service = _build_service(tmp_path)
    now = datetime.now(timezone.utc)
    await service.metadata_store.save_summary(
        {
            "captured_at": now.isoformat(),
            "total": 1,
            "due": 1,
            "successful": 1,
            "pending": 0,
            "first_seen_at": now.isoformat(),
            "last_success_at": now.isoformat(),
            "metadata_sample": [],
            "failed_count": 0,
            "failure_sample": [],
            "storage_doc_count": 3,
        }
    )
    service._cache_service = SimpleNamespace(
        get_fetcher_stats=lambda: {"fallback_attempts": 1, "fallback_successes": 0, "fallback_failures": 1}
    )

    snapshot = await service.get_status_snapshot()

    stats = snapshot["stats"]
    assert snapshot["scheduler_initialized"] is False
    assert snapshot["scheduler_running"] is False
    assert stats["metadata_total_urls"] == 1
    assert stats["metadata_due_urls"] == 1
    assert stats["fallback_attempts"] == 1
    assert "metadata_summary_missing" not in stats


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_returns_true_when_initialized(tmp_path) -> None:
    service = _build_service(tmp_path)
    service._initialized = True  # pylint: disable=protected-access

    assert await service.initialize() is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_returns_false_when_disabled(tmp_path) -> None:
    service = _build_service(tmp_path, enabled=False)

    assert await service.initialize() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_returns_false_when_no_urls(tmp_path) -> None:
    service = _build_service(tmp_path, urls=[])

    assert await service.initialize() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_starts_scheduler(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    service = _build_service(tmp_path)
    started = {"count": 0}

    class FakeScheduler:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def start(self) -> None:
            started["count"] += 1

    monkeypatch.setattr(
        "docs_mcp_server.services.scheduler_service.SyncScheduler",
        FakeScheduler,
    )

    assert await service.initialize() is True
    assert started["count"] == 1


@pytest.mark.unit
def test_get_cache_service_reuses_instance(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    service = _build_service(tmp_path)
    created: list[object] = []

    class FakeCacheService:
        def __init__(self, *args, **kwargs) -> None:
            created.append(self)

    monkeypatch.setattr(
        "docs_mcp_server.services.scheduler_service.CacheService",
        FakeCacheService,
    )

    first = service._get_cache_service()  # pylint: disable=protected-access
    second = service._get_cache_service()  # pylint: disable=protected-access

    assert first is second
    assert len(created) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_status_snapshot_marks_missing_summary(tmp_path) -> None:
    service = _build_service(tmp_path)

    snapshot = await service.get_status_snapshot()

    stats = snapshot["stats"]
    assert stats["metadata_total_urls"] == 0
    assert stats["metadata_due_urls"] == 0
    assert stats["metadata_summary_missing"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_closes_scheduler_and_cache(tmp_path) -> None:
    service = _build_service(tmp_path)

    async def stop() -> None:
        return None

    async def close() -> None:
        return None

    scheduler = SimpleNamespace(stop=stop)
    cache_service = SimpleNamespace(close=close)
    service._scheduler = scheduler
    service._cache_service = cache_service

    await service.stop()

    assert service._scheduler is None
    assert service._cache_service is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_returns_uninitialized(tmp_path) -> None:
    service = _build_service(tmp_path)

    response = await service.trigger_sync()

    assert response["success"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_rejects_when_running(tmp_path) -> None:
    service = _build_service(tmp_path)

    async def trigger_sync(**kwargs):
        return {"success": True}

    service._scheduler = SimpleNamespace(trigger_sync=trigger_sync)
    service._initialized = True  # pylint: disable=protected-access
    service._active_trigger_task = asyncio.create_task(asyncio.sleep(0.01))

    response = await service.trigger_sync()

    assert response["success"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_runs_in_background(tmp_path) -> None:
    service = _build_service(tmp_path)

    async def trigger_sync(**kwargs):
        return {"success": False}

    service._scheduler = SimpleNamespace(trigger_sync=trigger_sync)
    service._initialized = True  # pylint: disable=protected-access

    response = await service.trigger_sync()

    assert response["success"] is True

    if service._active_trigger_task is not None:
        await service._active_trigger_task
    assert service._active_trigger_task is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_logs_failure_result(tmp_path) -> None:
    service = _build_service(tmp_path)

    async def trigger_sync(**kwargs):
        return "bad-result"

    service._scheduler = SimpleNamespace(trigger_sync=trigger_sync)
    service._initialized = True  # pylint: disable=protected-access

    response = await service.trigger_sync()

    assert response["success"] is True

    if service._active_trigger_task is not None:
        await service._active_trigger_task
    assert service._active_trigger_task is None
