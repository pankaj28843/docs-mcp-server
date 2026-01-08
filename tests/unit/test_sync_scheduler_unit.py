from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.domain.sync_progress import SyncPhase, SyncProgress
from docs_mcp_server.utils.sync_metadata_store import LockLease, SyncMetadataStore
from docs_mcp_server.utils.sync_progress_store import SyncProgressStore
from docs_mcp_server.utils.sync_scheduler import SyncMetadata, SyncScheduler, SyncSchedulerConfig


def _import_sync_scheduler():
    from docs_mcp_server.utils import sync_scheduler

    return sync_scheduler


class _DummySettings(Settings):
    def __init__(self) -> None:
        super().__init__(docs_name="Docs", docs_sitemap_url=["https://example.com/sitemap.xml"])


class _InMemoryMetadataStore:
    def __init__(self, base_path: Path) -> None:
        self.metadata_root = base_path
        self._metadata: dict[str, dict] = {}
        self._snapshots: dict[str, dict] = {}

    def ensure_ready(self) -> None:
        return None

    async def cleanup_legacy_artifacts(self) -> None:
        return None

    async def save_last_sync_time(self, sync_time: datetime) -> None:
        self._metadata["__last_sync__"] = {"last_sync_at": sync_time.isoformat()}

    async def get_last_sync_time(self) -> datetime | None:
        payload = self._metadata.get("__last_sync__")
        if not payload:
            return None
        return datetime.fromisoformat(payload["last_sync_at"])

    async def save_sitemap_snapshot(self, snapshot: dict, snapshot_id: str) -> None:
        self._snapshots[snapshot_id] = dict(snapshot)

    async def get_sitemap_snapshot(self, snapshot_id: str) -> dict | None:
        return self._snapshots.get(snapshot_id)

    async def save_url_metadata(self, metadata: dict) -> None:
        url = metadata.get("url")
        if url:
            self._metadata[url] = dict(metadata)

    async def load_url_metadata(self, url: str) -> dict | None:
        return self._metadata.get(url)

    async def list_all_metadata(self) -> list[dict]:
        return [payload for key, payload in self._metadata.items() if key != "__last_sync__"]

    async def save_debug_snapshot(self, name: str, payload: dict) -> None:
        self._snapshots[name] = dict(payload)

    async def try_acquire_lock(self, name: str, owner: str, ttl_seconds: int):
        return None, None

    async def release_lock(self, lease: LockLease) -> None:
        return None

    async def break_lock(self, name: str) -> None:
        return None


def _progress_store_stub():
    class _StubStore:
        def __init__(self) -> None:
            self.saved: list[SyncProgress] = []
            self.checkpoints: list[dict] = []
            self.latest: SyncProgress | None = None

        async def save(self, progress):
            self.saved.append(progress)

        async def save_checkpoint(self, tenant_codename, checkpoint, *, keep_history: bool = False):
            self.checkpoints.append(checkpoint)

        async def get_latest_for_tenant(self, tenant_codename):
            return self.latest

    return _StubStore()


@dataclass
class DummyDoc:
    url: SimpleNamespace


class DummyDocuments:
    def __init__(self, count: int = 0, docs: list[DummyDoc] | None = None) -> None:
        self._count = count
        self._docs = docs or []
        self.deleted: list[str] = []

    async def count(self) -> int:
        return self._count

    async def list(self, limit: int = 100000) -> list[DummyDoc]:
        return list(self._docs)

    async def delete(self, url: str) -> None:
        self.deleted.append(url)


class DummyUoW:
    def __init__(self, documents: DummyDocuments) -> None:
        self.documents = documents
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self) -> None:
        self.committed = True


class DummyCacheService:
    def __init__(self, stats: dict | None = None) -> None:
        self._stats = stats or {"fallback_attempts": 1, "fallback_successes": 2, "fallback_failures": 3}

    def get_fetcher_stats(self) -> dict:
        return dict(self._stats)


class _FailureCacheService:
    async def check_and_fetch_page(self, url: str, *, use_semantic_cache: bool = True):
        raise RuntimeError("boom")

    def get_fetcher_stats(self) -> dict[str, int]:
        return {"fallback_attempts": 0, "fallback_successes": 0, "fallback_failures": 0}


def _build_scheduler(tmp_path, *, refresh_schedule: str | None = None) -> SyncScheduler:
    settings = Settings(
        docs_name="Docs",
        docs_entry_url=["https://example.com"],
    )
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    docs = DummyDocuments(count=2)

    def uow_factory() -> DummyUoW:
        return DummyUoW(docs)

    def cache_service_factory() -> DummyCacheService:
        return DummyCacheService()

    config = SyncSchedulerConfig(entry_urls=["https://example.com"], refresh_schedule=refresh_schedule)
    return SyncScheduler(
        settings=settings,
        uow_factory=uow_factory,
        cache_service_factory=cache_service_factory,
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=config,
    )


class _FetchStub:
    def __init__(self, *, page: object | None, was_cached: bool, reason: str | None) -> None:
        self.page = page
        self.was_cached = was_cached
        self.reason = reason
        self.called = False
        self.semantic_calls: list[bool] = []

    async def check_and_fetch_page(self, url: str, *, use_semantic_cache: bool = True):
        self.called = True
        self.semantic_calls.append(use_semantic_cache)
        return self.page, self.was_cached, self.reason

    def get_fetcher_stats(self) -> dict[str, int]:
        return {"fallback_attempts": 0, "fallback_successes": 0, "fallback_failures": 0}


@pytest.mark.unit
def test_determine_mode_entry_only(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    assert scheduler._determine_mode() == "entry"  # pylint: disable=protected-access


@pytest.mark.unit
def test_calculate_schedule_interval_hours_defaults(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    assert scheduler._calculate_schedule_interval_hours() == 24.0  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_returns_not_running(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    response = await scheduler.trigger_sync()

    assert response["success"] is False
    assert response["message"] == "Scheduler not running"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_success_calls_cycle(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.running = True
    called = {"ran": False}

    async def fake_cycle(*args, **kwargs) -> None:
        called["ran"] = True

    monkeypatch.setattr(scheduler, "_sync_cycle", fake_cycle)

    response = await scheduler.trigger_sync(force_crawler=True, force_full_sync=True)

    assert response["success"] is True
    assert called["ran"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_failure_returns_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.running = True

    async def raise_cycle(*args, **kwargs) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "_sync_cycle", raise_cycle)

    response = await scheduler.trigger_sync()

    assert response["success"] is False
    assert "Sync failed" in response["message"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_noops_when_running(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.running = True

    await scheduler.start()

    assert scheduler.running is True


@pytest.mark.unit
def test_calculate_next_due_respects_lastmod(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    now = datetime.now(timezone.utc)

    recent = scheduler._calculate_next_due(now - timedelta(days=2))  # pylint: disable=protected-access
    moderate = scheduler._calculate_next_due(now - timedelta(days=10))  # pylint: disable=protected-access
    stale = scheduler._calculate_next_due(now - timedelta(days=40))  # pylint: disable=protected-access

    assert 0.8 <= (recent - datetime.now(timezone.utc)).total_seconds() / 86400 <= 1.2
    assert 6 <= (moderate - datetime.now(timezone.utc)).days <= 8
    assert 25 <= (stale - datetime.now(timezone.utc)).days <= 31


@pytest.mark.unit
def test_calculate_next_due_adds_timezone_when_missing(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    naive = datetime(2024, 1, 1)

    next_due = scheduler._calculate_next_due(naive)  # pylint: disable=protected-access

    assert next_due.tzinfo is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mark_url_failed_updates_metadata(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access

    await scheduler._mark_url_failed("https://example.com/doc", reason="boom")  # pylint: disable=protected-access

    payload = await scheduler.metadata_store.load_url_metadata("https://example.com/doc")
    metadata = SyncMetadata.from_dict(payload)

    assert metadata.last_status == "failed"
    assert metadata.retry_count == 1
    assert scheduler.stats["urls_failed"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_metadata_clears_failure_on_success(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    now = datetime.now(timezone.utc)
    await scheduler.metadata_store.save_url_metadata(
        SyncMetadata(
            url="https://example.com/doc",
            last_status="failed",
            last_failure_reason="oops",
            last_failure_at=now,
            next_due_at=now,
        ).to_dict()
    )

    await scheduler._update_metadata(  # pylint: disable=protected-access
        url="https://example.com/doc",
        last_fetched_at=now,
        next_due_at=now,
        status="success",
        retry_count=0,
    )

    payload = await scheduler.metadata_store.load_url_metadata("https://example.com/doc")
    metadata = SyncMetadata.from_dict(payload)

    assert metadata.last_failure_reason is None
    assert metadata.last_failure_at is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_due_urls_filters_by_next_due(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    now = datetime.now(timezone.utc)

    entries = [
        SyncMetadata(url="https://due", next_due_at=now - timedelta(days=1)).to_dict(),
        SyncMetadata(url="https://later", next_due_at=now + timedelta(days=1)).to_dict(),
    ]

    due = await scheduler._get_due_urls(entries)  # pylint: disable=protected-access

    assert due == {"https://due"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_due_urls_skips_invalid_payloads(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    now = datetime.now(timezone.utc)

    entries = [
        {},
        SyncMetadata(url="https://due", next_due_at=now - timedelta(days=1)).to_dict(),
    ]

    due = await scheduler._get_due_urls(entries)  # pylint: disable=protected-access

    assert due == {"https://due"}


@pytest.mark.unit
def test_update_metadata_stats_records_failures(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    now = datetime.now(timezone.utc)

    entries = [
        SyncMetadata(url="https://ok", last_status="success", last_fetched_at=now, next_due_at=now).to_dict(),
        SyncMetadata(
            url="https://bad",
            last_status="failed",
            last_failure_reason="oops",
            last_failure_at=now,
            retry_count=2,
            next_due_at=now,
        ).to_dict(),
    ]

    scheduler._update_metadata_stats(entries)  # pylint: disable=protected-access

    assert scheduler.stats["metadata_total_urls"] == 2
    assert scheduler.stats["metadata_successful"] == 1
    assert scheduler.stats["failed_url_count"] == 1
    assert scheduler.stats["failure_sample"][0]["url"] == "https://bad"


@pytest.mark.unit
def test_parse_iso_timestamp_handles_invalid(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    parsed = scheduler._parse_iso_timestamp("not-a-date")  # pylint: disable=protected-access

    assert parsed is None


@pytest.mark.unit
def test_select_metadata_sample_sorts_by_due(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    now = datetime.now(timezone.utc)

    entries = [
        SyncMetadata(url="https://later", next_due_at=now + timedelta(days=2)).to_dict(),
        SyncMetadata(url="https://soon", next_due_at=now + timedelta(hours=1)).to_dict(),
    ]

    sample = scheduler._select_metadata_sample(entries, limit=1)  # pylint: disable=protected-access

    assert sample[0]["url"] == "https://soon"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_metadata_snapshot_empty_clears_stats(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    await scheduler._write_metadata_snapshot([])  # pylint: disable=protected-access

    assert scheduler.stats["metadata_snapshot_path"] is None
    assert scheduler.stats["metadata_sample"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_write_metadata_snapshot_persists_payload(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    entries = [SyncMetadata(url="https://example.com").to_dict()]

    await scheduler._write_metadata_snapshot(entries)  # pylint: disable=protected-access

    assert scheduler.stats["metadata_snapshot_path"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_sitemap_metadata_uses_snapshot(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    snapshot = {
        "entry_count": 5,
        "filtered_count": 2,
        "fetched_at": "2024-01-01T00:00:00+00:00",
        "content_hash": "abc",
    }
    await scheduler.metadata_store.save_sitemap_snapshot(snapshot, "current_sitemap")

    await scheduler._load_sitemap_metadata()  # pylint: disable=protected-access

    assert scheduler.sitemap_metadata["total_urls"] == 5
    assert scheduler.stats["sitemap_total_urls"] == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_sitemap_metadata_handles_missing_snapshot(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    await scheduler._load_sitemap_metadata()  # pylint: disable=protected-access

    assert scheduler.sitemap_metadata["total_urls"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_sitemap_snapshot_handles_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    async def raise_error(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler.metadata_store, "get_sitemap_snapshot", raise_error)

    snapshot = await scheduler._get_sitemap_snapshot("bad")  # pylint: disable=protected-access

    assert snapshot is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_sitemap_snapshot_handles_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    async def raise_error(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler.metadata_store, "save_sitemap_snapshot", raise_error)

    await scheduler._save_sitemap_snapshot({"entry_count": 0}, "bad")  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_and_check_sitemap_handles_request_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = Settings(docs_name="Docs", docs_sitemap_url=["https://example.com/sitemap.xml"])
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW(DummyDocuments(count=0)),
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(sitemap_urls=["https://example.com/sitemap.xml"]),
    )

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            raise RuntimeError("boom")

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.httpx, "AsyncClient", FakeAsyncClient)

    changed, entries = await scheduler._fetch_and_check_sitemap()  # pylint: disable=protected-access

    assert changed is False
    assert entries == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_cache_stats_sets_storage_count(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    await scheduler._update_cache_stats()  # pylint: disable=protected-access

    assert scheduler.stats["storage_doc_count"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_fetcher_metrics_updates_stats(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    scheduler._refresh_fetcher_metrics()  # pylint: disable=protected-access

    assert scheduler.stats["fallback_attempts"] == 1
    assert scheduler.stats["fallback_successes"] == 2
    assert scheduler.stats["fallback_failures"] == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_last_sync_time_handles_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    async def raise_error():
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler.metadata_store, "get_last_sync_time", raise_error)

    last_sync = await scheduler._get_last_sync_time()  # pylint: disable=protected-access

    assert last_sync is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_loop_records_error_and_backs_off(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path, refresh_schedule="*/5 * * * *")
    scheduler.running = True

    async def raise_error():
        raise RuntimeError("boom")

    async def fast_sleep(_seconds: float):
        scheduler.running = False

    monkeypatch.setattr(scheduler, "_get_last_sync_time", raise_error)

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.asyncio, "sleep", fast_sleep)

    await scheduler._run_loop()  # pylint: disable=protected-access

    assert scheduler.stats["errors"] >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_and_check_sitemap_filters_and_detects_changes(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = Settings(
        docs_name="Docs",
        docs_sitemap_url=["https://example.com/sitemap.xml"],
        url_whitelist_prefixes="https://example.com/docs/",
    )
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    def uow_factory() -> DummyUoW:
        return DummyUoW(DummyDocuments(count=0))

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=uow_factory,
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(sitemap_urls=["https://example.com/sitemap.xml"]),
    )

    xml_payload = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://example.com/docs/page1</loc><lastmod>2024-01-01</lastmod></url>"
        b"<url><loc>https://example.com/blog/post</loc></url>"
        b"</urlset>"
    )

    class FakeResponse:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            return FakeResponse(xml_payload)

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.httpx, "AsyncClient", FakeAsyncClient)

    changed, entries = await scheduler._fetch_and_check_sitemap()  # pylint: disable=protected-access

    assert changed is True
    assert len(entries) == 1

    changed_again, _ = await scheduler._fetch_and_check_sitemap()  # pylint: disable=protected-access
    assert changed_again is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_and_check_sitemap_handles_empty_response(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = Settings(docs_name="Docs", docs_sitemap_url=["https://example.com/sitemap.xml"])
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW(DummyDocuments(count=0)),
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(sitemap_urls=["https://example.com/sitemap.xml"]),
    )

    class FakeResponse:
        def __init__(self) -> None:
            self.content = b""

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            return FakeResponse()

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.httpx, "AsyncClient", FakeAsyncClient)

    changed, entries = await scheduler._fetch_and_check_sitemap()  # pylint: disable=protected-access

    assert changed is False
    assert entries == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_and_check_sitemap_handles_invalid_xml(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = Settings(docs_name="Docs", docs_sitemap_url=["https://example.com/sitemap.xml"])
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW(DummyDocuments(count=0)),
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(sitemap_urls=["https://example.com/sitemap.xml"]),
    )

    class FakeResponse:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            return FakeResponse(b"not xml")

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.httpx, "AsyncClient", FakeAsyncClient)

    changed, entries = await scheduler._fetch_and_check_sitemap()  # pylint: disable=protected-access

    assert changed is False
    assert entries == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_and_check_sitemap_handles_bad_lastmod(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = Settings(docs_name="Docs", docs_sitemap_url=["https://example.com/sitemap.xml"])
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW(DummyDocuments(count=0)),
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(sitemap_urls=["https://example.com/sitemap.xml"]),
    )

    xml_payload = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://example.com/docs/page</loc><lastmod>not-a-date</lastmod></url>"
        b"</urlset>"
    )

    class FakeResponse:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str):
            return FakeResponse(xml_payload)

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.httpx, "AsyncClient", FakeAsyncClient)

    changed, entries = await scheduler._fetch_and_check_sitemap()  # pylint: disable=protected-access

    assert changed is True
    assert entries[0].lastmod is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_entry_url_redirects_and_failures(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = Settings(
        docs_name="Docs",
        docs_entry_url=["https://example.com/docs/"],
        url_whitelist_prefixes="https://example.com/docs/",
    )
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW(DummyDocuments(count=0)),
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(entry_urls=["https://example.com/docs/", "https://example.com/redirect"]),
    )

    redirect_map = {"https://example.com/redirect": "https://example.com/docs/redirected"}

    class FakeHeadResponse:
        def __init__(self, url: str) -> None:
            self.url = url

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def head(self, url: str):
            if url.endswith("docs/"):
                return FakeHeadResponse(url)
            if url in redirect_map:
                return FakeHeadResponse(redirect_map[url])
            raise RuntimeError("boom")

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.httpx, "AsyncClient", FakeAsyncClient)

    resolved = await scheduler._resolve_entry_url_redirects(  # pylint: disable=protected-access
        ["https://example.com/docs/", "https://example.com/redirect", "https://example.com/fail"]
    )

    assert "https://example.com/docs/" in resolved
    assert "https://example.com/docs/redirected" in resolved


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_entry_url_redirects_filters_out_disallowed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = Settings(
        docs_name="Docs",
        docs_entry_url=["https://example.com/docs/"],
        url_whitelist_prefixes="https://example.com/docs/",
    )
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW(DummyDocuments(count=0)),
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(entry_urls=["https://example.com/redirect"]),
    )

    class FakeHeadResponse:
        def __init__(self, url: str) -> None:
            self.url = url

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def head(self, url: str):
            return FakeHeadResponse("https://blocked.example.com/")

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.httpx, "AsyncClient", FakeAsyncClient)

    resolved = await scheduler._resolve_entry_url_redirects(  # pylint: disable=protected-access
        ["https://example.com/redirect"]
    )

    assert resolved == set()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_entry_url_redirects_returns_original_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    settings = Settings(
        docs_name="Docs",
        docs_entry_url=["https://example.com/docs/"],
        url_whitelist_prefixes="https://example.com/docs/",
    )
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: DummyUoW(DummyDocuments(count=0)),
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(entry_urls=["https://example.com/docs/"]),
    )

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def head(self, url: str):
            raise RuntimeError("boom")

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.httpx, "AsyncClient", FakeAsyncClient)

    resolved = await scheduler._resolve_entry_url_redirects(  # pylint: disable=protected-access
        ["https://example.com/docs/"]
    )

    assert "https://example.com/docs/" in resolved


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discover_urls_from_entry_unions_crawl(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.entry_urls = ["https://example.com/docs/"]

    async def fake_resolve(entry_urls: list[str]) -> set[str]:
        return {"https://example.com/docs/"}

    async def fake_crawl(root_urls: set[str], force_crawl: bool = False) -> set[str]:
        return {"https://example.com/docs/a"}

    monkeypatch.setattr(scheduler, "_resolve_entry_url_redirects", fake_resolve)
    monkeypatch.setattr(scheduler, "_crawl_links_from_roots", fake_crawl)

    discovered = await scheduler._discover_urls_from_entry(force_crawl=True)  # pylint: disable=protected-access

    assert discovered == {"https://example.com/docs/", "https://example.com/docs/a"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discover_urls_from_entry_returns_empty_when_none(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.entry_urls = []

    discovered = await scheduler._discover_urls_from_entry()  # pylint: disable=protected-access

    assert discovered == set()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discover_urls_from_entry_handles_no_roots(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.entry_urls = ["https://example.com/docs/"]

    async def fake_resolve(entry_urls: list[str]) -> set[str]:
        return set()

    monkeypatch.setattr(scheduler, "_resolve_entry_url_redirects", fake_resolve)

    discovered = await scheduler._discover_urls_from_entry()  # pylint: disable=protected-access

    assert discovered == set()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_crawler_if_needed_respects_flags(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.mode = "entry"
    urls = await scheduler._apply_crawler_if_needed(  # pylint: disable=protected-access
        {"https://example.com"}, sitemap_changed=True, force_crawler=False
    )
    assert urls == {"https://example.com"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_crawler_if_needed_skips_when_cache_sufficient(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.mode = "sitemap"
    scheduler.settings.enable_crawler = True
    scheduler.stats["es_cached_count"] = 10
    scheduler.stats["filtered_urls"] = 1

    async def fake_has_previous(*args, **kwargs) -> bool:
        return True

    monkeypatch.setattr(scheduler, "_has_previous_metadata", fake_has_previous)

    urls = await scheduler._apply_crawler_if_needed(  # pylint: disable=protected-access
        {"https://example.com"}, sitemap_changed=False, force_crawler=False
    )

    assert urls == {"https://example.com"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_crawler_if_needed_skips_when_sitemap_changed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.mode = "sitemap"
    scheduler.settings.enable_crawler = True
    scheduler.stats["es_cached_count"] = 10
    scheduler.stats["filtered_urls"] = 1

    async def fake_has_previous(*args, **kwargs) -> bool:
        return True

    monkeypatch.setattr(scheduler, "_has_previous_metadata", fake_has_previous)

    urls = await scheduler._apply_crawler_if_needed(  # pylint: disable=protected-access
        {"https://example.com"}, sitemap_changed=True, force_crawler=False
    )

    assert urls == {"https://example.com"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_crawler_if_needed_runs_crawler(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.mode = "sitemap"
    scheduler.settings.enable_crawler = True
    scheduler.stats["es_cached_count"] = 0
    scheduler.stats["filtered_urls"] = 1

    async def fake_crawl(root_urls: set[str], force_crawl: bool = False) -> set[str]:
        return {"https://example.com/extra"}

    monkeypatch.setattr(scheduler, "_crawl_links_from_roots", fake_crawl)

    urls = await scheduler._apply_crawler_if_needed(  # pylint: disable=protected-access
        {"https://example.com"}, sitemap_changed=True, force_crawler=False, has_previous_metadata=False
    )

    assert "https://example.com/extra" in urls
    assert scheduler.stats["urls_discovered"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_crawler_if_needed_runs_when_no_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.mode = "sitemap"
    scheduler.settings.enable_crawler = True
    scheduler.stats["es_cached_count"] = 0
    scheduler.stats["filtered_urls"] = 1

    async def fake_crawl(root_urls: set[str], force_crawl: bool = False) -> set[str]:
        return {"https://example.com/extra"}

    monkeypatch.setattr(scheduler, "_crawl_links_from_roots", fake_crawl)

    urls = await scheduler._apply_crawler_if_needed(  # pylint: disable=protected-access
        {"https://example.com"}, sitemap_changed=False, force_crawler=False, has_previous_metadata=False
    )

    assert "https://example.com/extra" in urls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_crawler_if_needed_logs_skip_when_last_run_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.mode = "sitemap"
    scheduler.settings.enable_crawler = True
    scheduler.stats["es_cached_count"] = 0
    scheduler.stats["filtered_urls"] = 1
    scheduler.stats["last_crawler_run"] = None

    async def fake_crawl(root_urls: set[str], force_crawl: bool = False) -> set[str]:
        scheduler.stats["crawler_total_runs"] += 1
        return {"https://example.com/extra"}

    monkeypatch.setattr(scheduler, "_crawl_links_from_roots", fake_crawl)

    urls = await scheduler._apply_crawler_if_needed(  # pylint: disable=protected-access
        {"https://example.com"}, sitemap_changed=True, force_crawler=True, has_previous_metadata=False
    )

    assert "https://example.com/extra" in urls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_url_skips_recently_fetched(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access
    now = datetime.now(timezone.utc)
    await scheduler.metadata_store.save_url_metadata(
        SyncMetadata(
            url="https://example.com",
            last_status="success",
            last_fetched_at=now,
            next_due_at=now,
        ).to_dict()
    )

    fetch_stub = _FetchStub(page=object(), was_cached=False, reason=None)
    scheduler.cache_service_factory = lambda: fetch_stub

    await scheduler._process_url("https://example.com")  # pylint: disable=protected-access

    assert fetch_stub.called is False
    assert scheduler.stats["urls_skipped"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_url_success_updates_metadata(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access

    fetch_stub = _FetchStub(page=object(), was_cached=True, reason=None)
    scheduler.cache_service_factory = lambda: fetch_stub

    await scheduler._process_url("https://example.com")  # pylint: disable=protected-access

    payload = await scheduler.metadata_store.load_url_metadata("https://example.com")
    metadata = SyncMetadata.from_dict(payload)

    assert metadata.last_status == "success"
    assert scheduler.stats["urls_cached"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_url_handles_invalid_metadata(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access
    calls = {"count": 0}

    async def fake_load(url: str):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"url": url}
        return None

    scheduler.metadata_store.load_url_metadata = fake_load  # type: ignore[assignment]

    fetch_stub = _FetchStub(page=object(), was_cached=False, reason=None)
    scheduler.cache_service_factory = lambda: fetch_stub

    await scheduler._process_url("https://example.com")  # pylint: disable=protected-access

    assert scheduler.stats["urls_fetched"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_url_records_errors_on_exception(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access
    scheduler.cache_service_factory = lambda: _FailureCacheService()

    await scheduler._process_url("https://example.com")  # pylint: disable=protected-access

    assert scheduler.stats["errors"] >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_url_failure_marks_failed(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access

    fetch_stub = _FetchStub(page=None, was_cached=False, reason="boom")
    scheduler.cache_service_factory = lambda: fetch_stub

    await scheduler._process_url("https://example.com")  # pylint: disable=protected-access

    payload = await scheduler.metadata_store.load_url_metadata("https://example.com")
    metadata = SyncMetadata.from_dict(payload)

    assert metadata.last_status == "failed"
    assert scheduler.stats["urls_failed"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_cycle_runs_sitemap_mode(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    settings = Settings(
        docs_name="Docs",
        docs_sitemap_url=["https://example.com/sitemap.xml"],
    )
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)
    docs = DummyDocuments(count=0)

    def uow_factory() -> DummyUoW:
        return DummyUoW(docs)

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=uow_factory,
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(sitemap_urls=["https://example.com/sitemap.xml"]),
    )
    scheduler.settings.enable_crawler = False

    async def fake_fetch():
        entry = SimpleNamespace(url="https://example.com/docs", lastmod=None)
        return True, [entry]

    monkeypatch.setattr(scheduler, "_fetch_and_check_sitemap", fake_fetch)

    async def fake_process(*args, **kwargs):
        await asyncio.sleep(0)

    async def fake_blacklist():
        return {"checked": 0, "deleted": 0, "errors": 0}

    monkeypatch.setattr(scheduler, "_process_url", fake_process)
    monkeypatch.setattr(scheduler, "delete_blacklisted_caches", fake_blacklist)

    async def no_sleep(*args, **kwargs):
        return None

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.asyncio, "sleep", no_sleep)

    await scheduler._sync_cycle(force_full_sync=True)  # pylint: disable=protected-access

    assert scheduler.stats["total_syncs"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_cycle_entry_mode_sets_bypass(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.mode = "entry"
    scheduler.stats["metadata_successful"] = 0
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access

    async def fake_prepare():
        scheduler._active_progress = SyncProgress.create_new("demo")
        return scheduler._active_progress

    async def fake_discover(*args, **kwargs):
        return {"https://example.com"}

    async def fake_apply(urls, *args, **kwargs):
        return urls

    async def fake_process(*args, **kwargs):
        return None

    async def fake_blacklist():
        return {"checked": 0, "deleted": 0, "errors": 0}

    async def no_sleep(*args, **kwargs):
        return None

    monkeypatch.setattr(scheduler, "_prepare_progress_for_cycle", fake_prepare)
    monkeypatch.setattr(scheduler, "_discover_urls_from_entry", fake_discover)
    monkeypatch.setattr(scheduler, "_apply_crawler_if_needed", fake_apply)
    monkeypatch.setattr(scheduler, "_process_url", fake_process)
    monkeypatch.setattr(scheduler, "delete_blacklisted_caches", fake_blacklist)
    monkeypatch.setattr(scheduler, "_complete_progress", lambda: asyncio.sleep(0))
    monkeypatch.setattr(scheduler, "_checkpoint_progress", lambda *args, **kwargs: asyncio.sleep(0))

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.asyncio, "sleep", no_sleep)

    await scheduler._sync_cycle()  # pylint: disable=protected-access

    assert scheduler.stats["force_full_sync_active"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_acquire_crawler_lock_success(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    lease = await scheduler._acquire_crawler_lock()  # pylint: disable=protected-access

    assert lease is not None
    assert scheduler.stats["crawler_lock_status"] == "acquired"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_acquire_crawler_lock_contended_with_no_metadata(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    lock_path = scheduler.metadata_store._lock_path("crawler")  # pylint: disable=protected-access
    lock_path.write_text("{bad json}", encoding="utf-8")

    lease = await scheduler._acquire_crawler_lock()  # pylint: disable=protected-access

    assert lease is None
    assert scheduler.stats["crawler_lock_status"] == "contended"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_acquire_crawler_lock_contended(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    store = scheduler.metadata_store
    lock_path = store._lock_path("crawler")  # pylint: disable=protected-access
    now = datetime.now(timezone.utc)
    payload = {
        "name": "crawler",
        "owner": "other",
        "acquired_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
    }
    lock_path.write_text(json.dumps(payload), encoding="utf-8")

    lease = await scheduler._acquire_crawler_lock()  # pylint: disable=protected-access

    assert lease is None
    assert scheduler.stats["crawler_lock_status"] == "contended"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_acquire_crawler_lock_stale_reacquires(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    store = scheduler.metadata_store
    lock_path = store._lock_path("crawler")  # pylint: disable=protected-access
    now = datetime.now(timezone.utc)
    payload = {
        "name": "crawler",
        "owner": "other",
        "acquired_at": (now - timedelta(hours=2)).isoformat(),
        "expires_at": (now - timedelta(hours=1)).isoformat(),
    }
    lock_path.write_text(json.dumps(payload), encoding="utf-8")

    async def not_recent() -> bool:
        return False

    monkeypatch.setattr(scheduler, "_tenant_recently_refreshed", not_recent)

    lease = await scheduler._acquire_crawler_lock()  # pylint: disable=protected-access

    assert lease is not None
    assert scheduler.stats["crawler_lock_status"] == "acquired"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_acquire_crawler_lock_stale_skips_when_recent(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    scheduler = _build_scheduler(tmp_path)
    store = scheduler.metadata_store
    lock_path = store._lock_path("crawler")  # pylint: disable=protected-access
    now = datetime.now(timezone.utc)
    payload = {
        "name": "crawler",
        "owner": "other",
        "acquired_at": (now - timedelta(hours=2)).isoformat(),
        "expires_at": (now - timedelta(hours=1)).isoformat(),
    }
    lock_path.write_text(json.dumps(payload), encoding="utf-8")

    async def is_recent() -> bool:
        return True

    monkeypatch.setattr(scheduler, "_tenant_recently_refreshed", is_recent)

    lease = await scheduler._acquire_crawler_lock()  # pylint: disable=protected-access

    assert lease is None
    assert scheduler.stats["crawler_lock_status"] == "stale"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_acquire_crawler_lock_stale_reacquire_fails(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    now = datetime.now(timezone.utc)
    stale = LockLease(
        name="crawler",
        owner="other",
        acquired_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
        path=Path("dummy"),
    )
    calls = {"count": 0}

    async def fake_try(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return None, stale
        return None, None

    async def not_recent() -> bool:
        return False

    monkeypatch.setattr(scheduler.metadata_store, "try_acquire_lock", fake_try)
    monkeypatch.setattr(scheduler, "_tenant_recently_refreshed", not_recent)

    lease = await scheduler._acquire_crawler_lock()  # pylint: disable=protected-access

    assert lease is None
    assert scheduler.stats["crawler_lock_status"] == "contended"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_crawl_links_from_roots_filters_and_records(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.settings.enable_crawler = True
    scheduler.settings.url_whitelist_prefixes = "https://example.com/docs/"

    async def fake_process(url: str, sitemap_lastmod=None):
        return None

    monkeypatch.setattr(scheduler, "_process_url", fake_process)

    class FakeCrawler:
        def __init__(self, root_urls, config) -> None:
            self._root_urls = root_urls
            self._config = config
            self._crawler_skipped = 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def crawl(self) -> set[str]:
            self._config.on_url_discovered("https://example.com/docs/queued")
            return set(self._root_urls) | {
                "https://example.com/docs/a",
                "https://example.com/blocked",
            }

    async def fake_acquire():
        now = datetime.now(timezone.utc)
        return LockLease(
            name="crawler",
            owner="owner",
            acquired_at=now,
            expires_at=now + timedelta(minutes=5),
            path=scheduler.metadata_store._lock_path("crawler"),  # pylint: disable=protected-access
        )

    monkeypatch.setattr(scheduler, "_acquire_crawler_lock", fake_acquire)

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler, "EfficientCrawler", FakeCrawler)

    discovered = await scheduler._crawl_links_from_roots({"https://example.com/docs/"})  # pylint: disable=protected-access

    assert "https://example.com/docs/a" in discovered


@pytest.mark.unit
@pytest.mark.asyncio
async def test_crawl_links_from_roots_handles_queue_errors(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.settings.enable_crawler = True

    async def fake_process(url: str, sitemap_lastmod=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "_process_url", fake_process)

    class FakeCrawler:
        def __init__(self, root_urls, config) -> None:
            self._config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def crawl(self) -> set[str]:
            self._config.on_url_discovered("https://example.com/docs/a")
            return {"https://example.com/docs/a"}

    async def fake_acquire():
        now = datetime.now(timezone.utc)
        return LockLease(
            name="crawler",
            owner="owner",
            acquired_at=now,
            expires_at=now + timedelta(minutes=5),
            path=scheduler.metadata_store._lock_path("crawler"),  # pylint: disable=protected-access
        )

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler, "EfficientCrawler", FakeCrawler)
    monkeypatch.setattr(scheduler, "_acquire_crawler_lock", fake_acquire)

    discovered = await scheduler._crawl_links_from_roots({"https://example.com/docs/"})  # pylint: disable=protected-access

    assert "https://example.com/docs/a" in discovered


@pytest.mark.unit
@pytest.mark.asyncio
async def test_crawl_links_from_roots_checks_recently_visited(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.settings.enable_crawler = True

    url = "https://example.com/docs/recent"
    digest = hashlib.sha256(url.encode()).hexdigest()
    meta_path = scheduler.metadata_store.metadata_root / f"url_{digest}.json"
    meta_path.write_text(
        json.dumps(
            {
                "url": url,
                "last_fetched_at": datetime.now(timezone.utc).isoformat(),
                "last_status": "success",
            }
        ),
        encoding="utf-8",
    )

    seen = {"skip_recent": None, "skip_missing": None}

    class FakeCrawler:
        def __init__(self, root_urls, config) -> None:
            self._config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def crawl(self) -> set[str]:
            seen["skip_recent"] = self._config.skip_recently_visited(url)
            seen["skip_missing"] = self._config.skip_recently_visited("https://example.com/docs/new")
            return {url}

    async def fake_acquire():
        now = datetime.now(timezone.utc)
        return LockLease(
            name="crawler",
            owner="owner",
            acquired_at=now,
            expires_at=now + timedelta(minutes=5),
            path=scheduler.metadata_store._lock_path("crawler"),  # pylint: disable=protected-access
        )

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler, "EfficientCrawler", FakeCrawler)
    monkeypatch.setattr(scheduler, "_acquire_crawler_lock", fake_acquire)

    await scheduler._crawl_links_from_roots({"https://example.com/docs/"})  # pylint: disable=protected-access

    assert seen["skip_recent"] is True
    assert seen["skip_missing"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_progress_for_cycle_resumes_interrupted(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    progress_store = _progress_store_stub()
    scheduler.progress_store = progress_store
    progress = SyncProgress.create_new("demo")
    progress.phase = SyncPhase.INTERRUPTED
    progress_store.latest = progress

    await scheduler._prepare_progress_for_cycle()  # pylint: disable=protected-access

    assert scheduler._active_progress is progress  # pylint: disable=protected-access
    assert progress.phase == SyncPhase.FETCHING


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_progress_for_cycle_starts_discovery(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    progress_store = _progress_store_stub()
    scheduler.progress_store = progress_store
    progress_store.latest = None

    progress = await scheduler._prepare_progress_for_cycle()  # pylint: disable=protected-access

    assert progress.phase == SyncPhase.DISCOVERING


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_metadata_can_be_accessed_errors(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    class ErrorUoW(DummyUoW):
        async def __aenter__(self):
            raise RuntimeError("boom")

    scheduler.uow_factory = lambda: ErrorUoW(DummyDocuments(count=0))

    with pytest.raises(RuntimeError):
        await scheduler._ensure_metadata_can_be_accessed()  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_checkpoint_progress_skips_when_recent(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    progress_store = _progress_store_stub()
    scheduler.progress_store = progress_store
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access
    scheduler._last_progress_checkpoint = datetime.now(timezone.utc)  # pylint: disable=protected-access

    await scheduler._checkpoint_progress(force=False)  # pylint: disable=protected-access

    assert progress_store.checkpoints == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_progress_skipped_noop_without_progress(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler._active_progress = None  # pylint: disable=protected-access

    await scheduler._record_progress_skipped("https://example.com", "skip")  # pylint: disable=protected-access

    assert scheduler.stats["queue_depth"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_complete_progress_handles_callback_error(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access

    async def raise_error() -> None:
        raise RuntimeError("boom")

    scheduler._on_sync_complete = raise_error  # pylint: disable=protected-access

    await scheduler._complete_progress()  # pylint: disable=protected-access

    assert scheduler._active_progress is None  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_blacklisted_caches_no_blacklist(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.settings.url_blacklist_prefixes = ""

    stats = await scheduler.delete_blacklisted_caches()

    assert stats["checked"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_blacklisted_caches_handles_delete_error(tmp_path) -> None:
    settings = Settings(
        docs_name="Docs",
        docs_entry_url=["https://example.com"],
        url_blacklist_prefixes="https://example.com/bad",
    )
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    class ErrorDocuments(DummyDocuments):
        async def delete(self, url: str) -> None:
            raise RuntimeError("boom")

    docs = ErrorDocuments(
        docs=[DummyDoc(url=SimpleNamespace(value="https://example.com/bad/doc"))],
    )

    def uow_factory() -> DummyUoW:
        return DummyUoW(docs)

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=uow_factory,
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(entry_urls=["https://example.com"]),
    )

    stats = await scheduler.delete_blacklisted_caches()

    assert stats["errors"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_blacklisted_caches_handles_uow_error(tmp_path) -> None:
    settings = Settings(
        docs_name="Docs",
        docs_entry_url=["https://example.com"],
        url_blacklist_prefixes="https://example.com/bad",
    )
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    class ErrorUoW(DummyUoW):
        async def __aenter__(self):
            raise RuntimeError("boom")

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=lambda: ErrorUoW(DummyDocuments(count=0)),
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(entry_urls=["https://example.com"]),
    )

    stats = await scheduler.delete_blacklisted_caches()

    assert stats["errors"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_blacklisted_caches_removes_matches(tmp_path) -> None:
    settings = Settings(
        docs_name="Docs",
        docs_entry_url=["https://example.com"],
        url_blacklist_prefixes="https://blocked/",
    )
    metadata_store = SyncMetadataStore(tmp_path)
    progress_store = SyncProgressStore(tmp_path)

    docs = DummyDocuments(
        docs=[
            DummyDoc(url=SimpleNamespace(value="https://blocked/doc")),
            DummyDoc(url=SimpleNamespace(value="https://allowed/doc")),
        ]
    )

    def uow_factory() -> DummyUoW:
        return DummyUoW(docs)

    scheduler = SyncScheduler(
        settings=settings,
        uow_factory=uow_factory,
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=metadata_store,
        progress_store=progress_store,
        tenant_codename="demo",
        config=SyncSchedulerConfig(entry_urls=["https://example.com"]),
    )

    stats = await scheduler.delete_blacklisted_caches()

    assert stats["checked"] == 2
    assert stats["deleted"] == 1
    assert docs.deleted == ["https://blocked/doc"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_loop_no_cron_returns_when_stopped(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.running = True

    async def fake_wait_for(awaitable, timeout):
        scheduler.running = False
        raise TimeoutError

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.asyncio, "wait_for", fake_wait_for)

    await scheduler._run_loop()  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_loop_with_cron_triggers_sync(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path, refresh_schedule="0 * * * *")
    scheduler.running = True

    class FakeSchedule:
        def __init__(self) -> None:
            self._calls = 0

        def next(self):
            self._calls += 1
            return datetime.now(timezone.utc) - timedelta(seconds=1)

    class FakeCron:
        def schedule(self, start_date):
            return FakeSchedule()

    scheduler.cron_instance = FakeCron()

    async def fake_sync_cycle(*args, **kwargs):
        scheduler.running = False

    monkeypatch.setattr(scheduler, "_sync_cycle", fake_sync_cycle)
    monkeypatch.setattr(scheduler, "_save_last_sync_time", lambda *args, **kwargs: asyncio.sleep(0))

    await scheduler._run_loop()  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trigger_sync_reports_failure(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.running = True

    async def fail_sync(*args, **kwargs):
        raise RuntimeError("boom")

    scheduler._sync_cycle = fail_sync  # type: ignore[assignment]

    response = await scheduler.trigger_sync()

    assert response["success"] is False
    assert "Sync failed" in response["message"]


@pytest.mark.unit
def test_sync_scheduler_requires_urls(tmp_path) -> None:
    settings = Settings(docs_name="Docs", docs_entry_url=["https://example.com"])

    with pytest.raises(ValueError, match="sitemap_urls or entry_urls"):
        SyncScheduler(
            settings=settings,
            uow_factory=lambda: DummyUoW(DummyDocuments()),
            cache_service_factory=lambda: DummyCacheService(),
            metadata_store=SyncMetadataStore(tmp_path),
            progress_store=SyncProgressStore(tmp_path),
            tenant_codename="demo",
            config=SyncSchedulerConfig(),
        )


@pytest.mark.unit
def test_determine_mode_hybrid(tmp_path) -> None:
    scheduler = SyncScheduler(
        settings=Settings(docs_name="Docs", docs_entry_url=["https://example.com"]),
        uow_factory=lambda: DummyUoW(DummyDocuments()),
        cache_service_factory=lambda: DummyCacheService(),
        metadata_store=SyncMetadataStore(tmp_path),
        progress_store=SyncProgressStore(tmp_path),
        tenant_codename="demo",
        config=SyncSchedulerConfig(
            sitemap_urls=["https://example.com/sitemap.xml"],
            entry_urls=["https://example.com/"],
        ),
    )

    assert scheduler._determine_mode() == "hybrid"  # pylint: disable=protected-access


@pytest.mark.unit
def test_calculate_schedule_interval_hours_handles_failure(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path, refresh_schedule="0 * * * *")

    class BadCron:
        def schedule(self, start_date):
            raise RuntimeError("boom")

    scheduler.cron_instance = BadCron()

    assert scheduler._calculate_schedule_interval_hours() == 24.0  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_sets_running_and_task(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(scheduler, "_ensure_metadata_can_be_accessed", noop)
    monkeypatch.setattr(scheduler, "_update_cache_stats", noop)
    monkeypatch.setattr(scheduler, "_run_loop", noop)

    await scheduler.start()

    assert scheduler.running is True
    assert scheduler.task is not None
    await scheduler.task


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_loop_sleeps_until_next_run(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path, refresh_schedule="0 * * * *")
    scheduler.running = True

    class FakeSchedule:
        def next(self):
            return datetime.now(timezone.utc) + timedelta(seconds=10)

    class FakeCron:
        def schedule(self, start_date):
            return FakeSchedule()

    scheduler.cron_instance = FakeCron()

    async def fake_sleep(seconds: float):
        scheduler.running = False

    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.asyncio, "sleep", fake_sleep)

    await scheduler._run_loop()  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_last_sync_time_handles_errors(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    async def raise_error():
        raise RuntimeError("boom")

    scheduler.metadata_store.get_last_sync_time = raise_error  # type: ignore[assignment]

    assert await scheduler._get_last_sync_time() is None  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_last_sync_time_handles_errors(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    async def raise_error(sync_time):
        raise RuntimeError("boom")

    scheduler.metadata_store.save_last_sync_time = raise_error  # type: ignore[assignment]

    await scheduler._save_last_sync_time(datetime.now(timezone.utc))  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_cycle_entry_mode_with_blacklist(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.mode = "entry"

    async def fake_discover(*args, **kwargs):
        return {"https://example.com/doc"}

    async def fake_process(*args, **kwargs):
        return None

    async def fake_blacklist():
        return {"checked": 1, "deleted": 1, "errors": 0}

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(scheduler, "_discover_urls_from_entry", fake_discover)
    monkeypatch.setattr(scheduler, "_process_url", fake_process)
    monkeypatch.setattr(scheduler, "delete_blacklisted_caches", fake_blacklist)
    monkeypatch.setattr(scheduler, "_update_cache_stats", noop)
    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler.asyncio, "sleep", noop)

    await scheduler._sync_cycle()  # pylint: disable=protected-access

    assert scheduler.stats["schedule_interval_hours_effective"] >= 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_crawler_if_needed_suppresses_when_cache_sufficient(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.mode = "sitemap"
    scheduler.settings.enable_crawler = True
    scheduler.stats["es_cached_count"] = 5
    scheduler.stats["filtered_urls"] = 1

    urls = await scheduler._apply_crawler_if_needed(  # pylint: disable=protected-access
        {"https://example.com"},
        sitemap_changed=True,
        force_crawler=False,
        has_previous_metadata=True,
    )

    assert urls == {"https://example.com"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_apply_crawler_if_needed_force_crawler(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler.mode = "sitemap"
    scheduler.settings.enable_crawler = True

    async def fake_crawl(root_urls: set[str], force_crawl: bool = False) -> set[str]:
        return {"https://example.com/extra"}

    monkeypatch.setattr(scheduler, "_crawl_links_from_roots", fake_crawl)

    urls = await scheduler._apply_crawler_if_needed(  # pylint: disable=protected-access
        {"https://example.com"},
        sitemap_changed=False,
        force_crawler=True,
        has_previous_metadata=True,
    )

    assert "https://example.com/extra" in urls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_crawl_links_from_roots_skips_without_lock(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    async def no_lock():
        return None

    monkeypatch.setattr(scheduler, "_acquire_crawler_lock", no_lock)

    discovered = await scheduler._crawl_links_from_roots({"https://example.com"})  # pylint: disable=protected-access

    assert discovered == set()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_crawl_links_from_roots_handles_crawl_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    async def fake_process(url: str, sitemap_lastmod=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler, "_process_url", fake_process)

    class FakeCrawler:
        def __init__(self, root_urls, config) -> None:
            self._config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def crawl(self):
            raise RuntimeError("boom")

    async def fake_acquire():
        now = datetime.now(timezone.utc)
        return LockLease(
            name="crawler",
            owner="owner",
            acquired_at=now,
            expires_at=now + timedelta(minutes=5),
            path=scheduler.metadata_store._lock_path("crawler"),  # pylint: disable=protected-access
        )

    monkeypatch.setattr(scheduler, "_acquire_crawler_lock", fake_acquire)
    sync_scheduler = _import_sync_scheduler()
    monkeypatch.setattr(sync_scheduler, "EfficientCrawler", FakeCrawler)

    discovered = await scheduler._crawl_links_from_roots({"https://example.com"})  # pylint: disable=protected-access

    assert discovered == set()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_url_invalid_metadata_falls_back(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access

    calls = {"count": 0}

    async def load_url_metadata(url: str):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"url": url, "first_seen_at": "bad", "next_due_at": "bad"}
        return None

    scheduler.metadata_store.load_url_metadata = load_url_metadata  # type: ignore[assignment]

    fetch_stub = _FetchStub(page=object(), was_cached=False, reason=None)
    scheduler.cache_service_factory = lambda: fetch_stub

    await scheduler._process_url("https://example.com")  # pylint: disable=protected-access

    assert fetch_stub.called is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_url_bypass_idempotency(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    scheduler._active_progress = SyncProgress.create_new("demo")  # pylint: disable=protected-access
    scheduler._bypass_idempotency = True  # pylint: disable=protected-access

    fetch_stub = _FetchStub(page=object(), was_cached=False, reason=None)
    scheduler.cache_service_factory = lambda: fetch_stub

    await scheduler._process_url("https://example.com")  # pylint: disable=protected-access

    assert fetch_stub.semantic_calls == [False]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_due_urls_skips_invalid_payload(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    due = await scheduler._get_due_urls([{"bad": "payload"}])  # pylint: disable=protected-access
    assert due == set()


@pytest.mark.unit
def test_parse_iso_timestamp_invalid(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    assert scheduler._parse_iso_timestamp("bad") is None  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_sitemap_snapshot_handles_errors(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    async def raise_error(snapshot_id):
        raise RuntimeError("boom")

    scheduler.metadata_store.get_sitemap_snapshot = raise_error  # type: ignore[assignment]

    assert await scheduler._get_sitemap_snapshot() is None  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_sitemap_snapshot_handles_errors(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)

    async def raise_error(snapshot, snapshot_id):
        raise RuntimeError("boom")

    scheduler.metadata_store.save_sitemap_snapshot = raise_error  # type: ignore[assignment]

    await scheduler._save_sitemap_snapshot({"ok": True})  # pylint: disable=protected-access


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tenant_recently_refreshed(tmp_path) -> None:
    scheduler = _build_scheduler(tmp_path)
    await scheduler.metadata_store.save_last_sync_time(datetime.now(timezone.utc))

    assert await scheduler._tenant_recently_refreshed() is True  # pylint: disable=protected-access
