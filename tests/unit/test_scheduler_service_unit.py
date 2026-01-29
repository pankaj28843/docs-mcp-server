from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.services.scheduler_service import SchedulerService, SchedulerServiceConfig
from docs_mcp_server.utils.crawl_state_store import CrawlStateStore


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
    metadata_store = CrawlStateStore(tmp_path)
    progress_store = metadata_store

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

    assert service.stats == {}


@pytest.mark.unit
def test_stats_returns_dict_from_scheduler(tmp_path) -> None:
    service = _build_service(tmp_path)
    service._scheduler = SimpleNamespace(stats={"ok": True})

    assert service.stats == {"ok": True}


@pytest.mark.unit
def test_stats_returns_empty_for_non_dict(tmp_path) -> None:
    service = _build_service(tmp_path)
    service._scheduler = SimpleNamespace(stats=["bad"])

    assert service.stats == {}


@pytest.mark.unit
def test_stats_returns_dataclass_payload(tmp_path) -> None:
    service = _build_service(tmp_path)

    @dataclass
    class _Stats:
        value: int

    service._scheduler = SimpleNamespace(stats=_Stats(value=2))

    assert service.stats == {"value": 2}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_status_snapshot_uses_crawl_snapshot_over_scheduler_stats(tmp_path) -> None:
    service = _build_service(tmp_path)
    service._scheduler = SimpleNamespace(stats={"queue_depth": 99, "metadata_total_urls": 99, "extra": "ok"})
    await service.metadata_store.upsert_url_metadata(
        {
            "url": "https://example.com/doc",
            "last_status": "success",
            "last_fetched_at": datetime.now(timezone.utc).isoformat(),
            "next_due_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        }
    )
    await service.metadata_store.enqueue_urls({"https://example.com/doc"}, reason="test", force=True)

    snapshot = await service.get_status_snapshot()

    assert snapshot["scheduler_initialized"] is True
    assert snapshot["scheduler_running"] is False
    assert snapshot["stats"]["queue_depth"] == 1
    assert snapshot["stats"]["metadata_total_urls"] == 1
    assert snapshot["stats"]["extra"] == "ok"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_status_snapshot_builds_fallback_when_uninitialized(tmp_path) -> None:
    service = _build_service(tmp_path)
    now = datetime.now(timezone.utc)
    await service.metadata_store.upsert_url_metadata(
        {
            "url": "https://example.com/doc",
            "last_status": "success",
            "last_fetched_at": now.isoformat(),
            "next_due_at": now.isoformat(),
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


@pytest.mark.unit
def test_parse_iso_timestamp_handles_invalid(tmp_path) -> None:
    service = _build_service(tmp_path)

    assert service._parse_iso_timestamp("not-a-date") is None  # pylint: disable=protected-access


@pytest.mark.unit
def test_parse_iso_timestamp_handles_missing_value(tmp_path) -> None:
    service = _build_service(tmp_path)

    assert service._parse_iso_timestamp(None) is None  # pylint: disable=protected-access


@pytest.mark.unit
def test_parse_iso_timestamp_handles_naive(tmp_path) -> None:
    service = _build_service(tmp_path)

    parsed = service._parse_iso_timestamp("2024-01-01T00:00:00")  # pylint: disable=protected-access

    assert parsed is not None
    assert parsed.tzinfo is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_returns_true_when_initialized(tmp_path) -> None:
    service = _build_service(tmp_path)
    service._scheduler = SimpleNamespace()

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
async def test_get_status_snapshot_empty_when_no_urls(tmp_path) -> None:
    service = _build_service(tmp_path)

    snapshot = await service.get_status_snapshot()

    stats = snapshot["stats"]
    assert stats["metadata_total_urls"] == 0
    assert stats["metadata_due_urls"] == 0
    assert stats["queue_depth"] == 0


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

    response = await service.trigger_sync()

    assert response["success"] is True

    if service._active_trigger_task is not None:
        await service._active_trigger_task
    assert service._active_trigger_task is None
