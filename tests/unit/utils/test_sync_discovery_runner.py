"""Unit tests for SyncDiscoveryRunner edge cases."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from docs_mcp_server.utils.sync_discovery_runner import SyncDiscoveryRunner


class _FakeCrawler:
    def __init__(self, root_urls, crawl_config):
        self._root_urls = root_urls
        self._crawl_config = crawl_config
        self._crawler_skipped = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def crawl(self):
        url = "https://example.com/discovered"
        if self._crawl_config.skip_recently_visited:
            if self._crawl_config.skip_recently_visited(url):
                self._crawler_skipped += 1
        if self._crawl_config.on_url_discovered:
            self._crawl_config.on_url_discovered(url)
        return set(self._root_urls) | {url}


class _FakeCrawlerMany(_FakeCrawler):
    def __init__(self, root_urls, crawl_config, count):
        super().__init__(root_urls, crawl_config)
        self._count = count

    async def crawl(self):
        urls = set(self._root_urls)
        for i in range(self._count):
            url = f"https://example.com/discovered/{i}"
            urls.add(url)
            if self._crawl_config.on_url_discovered:
                self._crawl_config.on_url_discovered(url)
        return urls


class _FakeCrawlerEmpty(_FakeCrawler):
    async def crawl(self):
        return set(self._root_urls)


def _make_settings():
    return SimpleNamespace(
        max_crawl_pages=10,
        markdown_url_suffix="",
        crawler_playwright_first=False,
        get_random_user_agent=lambda: "agent",
        should_process_url=lambda url: True,
        crawler_min_concurrency=1,
        crawler_max_concurrency=2,
        crawler_max_sessions=2,
    )


def _make_stats():
    return SimpleNamespace(
        discovery_root_urls=0,
        discovery_discovered=0,
        discovery_filtered=0,
        discovery_progressively_processed=0,
        last_crawler_run=None,
        crawler_total_runs=0,
        discovery_sample=[],
    )


class _MetaStore:
    def __init__(self, root):
        self.metadata_root = root

    async def release_lock(self, _lease):
        return None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_handles_progressive_processor_error(monkeypatch, tmp_path):
    async def _process_url(_url, _reason):
        raise RuntimeError("boom")

    stats = _make_stats()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=_MetaStore(tmp_path),
        stats=stats,
        schedule_interval_hours=1,
        process_url_callback=_process_url,
        acquire_crawler_lock_callback=lambda: asyncio.sleep(0, result="lease"),
    )

    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler", _FakeCrawler)
    monkeypatch.setattr(
        "docs_mcp_server.utils.sync_discovery_runner.asyncio.get_event_loop",
        lambda: SimpleNamespace(call_soon_threadsafe=lambda fn, arg: fn(arg)),
    )

    result = await runner.run({"https://example.com/root"})

    assert "https://example.com/discovered" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_handles_queueing_failure(monkeypatch, tmp_path):
    async def _process_url(_url, _reason):
        return None

    def _raise(*_args, **_kwargs):
        raise RuntimeError("queue boom")

    stats = _make_stats()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=_MetaStore(tmp_path),
        stats=stats,
        schedule_interval_hours=1,
        process_url_callback=_process_url,
        acquire_crawler_lock_callback=lambda: asyncio.sleep(0, result="lease"),
    )

    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler", _FakeCrawler)
    monkeypatch.setattr(
        "docs_mcp_server.utils.sync_discovery_runner.asyncio.get_event_loop",
        lambda: SimpleNamespace(call_soon_threadsafe=_raise),
    )

    result = await runner.run({"https://example.com/root"})

    assert "https://example.com/discovered" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_handles_recently_visited_parse_error(monkeypatch, tmp_path):
    async def _process_url(_url, _reason):
        return None

    digest = hashlib.sha256(b"https://example.com/discovered").hexdigest()
    meta_path = tmp_path / f"url_{digest}.json"
    meta_path.write_text("{bad json", encoding="utf-8")

    stats = _make_stats()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=_MetaStore(tmp_path),
        stats=stats,
        schedule_interval_hours=1,
        process_url_callback=_process_url,
        acquire_crawler_lock_callback=lambda: asyncio.sleep(0, result="lease"),
    )

    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler", _FakeCrawler)
    monkeypatch.setattr(
        "docs_mcp_server.utils.sync_discovery_runner.json.loads",
        lambda *_args: (_ for _ in ()).throw(ValueError("bad")),
    )

    result = await runner.run({"https://example.com/root"})

    assert result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_records_progressive_batch(monkeypatch, tmp_path):
    async def _process_url(_url, _reason):
        return None

    stats = _make_stats()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=_MetaStore(tmp_path),
        stats=stats,
        schedule_interval_hours=1,
        process_url_callback=_process_url,
        acquire_crawler_lock_callback=lambda: asyncio.sleep(0, result="lease"),
    )

    monkeypatch.setattr(
        "docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler",
        lambda root_urls, crawl_config: _FakeCrawlerMany(root_urls, crawl_config, 50),
    )
    monkeypatch.setattr(
        "docs_mcp_server.utils.sync_discovery_runner.asyncio.get_event_loop",
        lambda: SimpleNamespace(call_soon_threadsafe=lambda fn, arg: fn(arg)),
    )

    result = await runner.run({"https://example.com/root"})

    assert len(result) == 50
    assert stats.discovery_progressively_processed == 50


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_handles_recently_visited_failure_status(monkeypatch, tmp_path):
    async def _process_url(_url, _reason):
        return None

    url = "https://example.com/discovered"
    digest = hashlib.sha256(url.encode()).hexdigest()
    meta_path = tmp_path / f"url_{digest}.json"
    meta_path.write_text(
        json.dumps({"last_fetched_at": datetime.now(timezone.utc).isoformat(), "last_status": "failed"}),
        encoding="utf-8",
    )

    stats = _make_stats()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=_MetaStore(tmp_path),
        stats=stats,
        schedule_interval_hours=1,
        process_url_callback=_process_url,
        acquire_crawler_lock_callback=lambda: asyncio.sleep(0, result="lease"),
    )

    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler", _FakeCrawler)

    result = await runner.run({"https://example.com/root"})

    assert url in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_handles_progressive_timeout(monkeypatch, tmp_path):
    async def _process_url(_url, _reason):
        return None

    class _ImmediateQueue:
        async def get(self):
            return None

        def put_nowait(self, _item):
            return None

        async def put(self, _item):
            return None

    stats = _make_stats()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=_MetaStore(tmp_path),
        stats=stats,
        schedule_interval_hours=1,
        process_url_callback=_process_url,
        acquire_crawler_lock_callback=lambda: asyncio.sleep(0, result="lease"),
    )

    calls = {"count": 0}

    async def _wait_for(_coro, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise asyncio.TimeoutError
        return await _coro

    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler", _FakeCrawlerEmpty)
    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.asyncio.wait_for", _wait_for)
    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.asyncio.Queue", _ImmediateQueue)

    result = await runner.run({"https://example.com/root"})

    assert result == set()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_handles_queue_put_and_task_failure(monkeypatch, tmp_path):
    async def _process_url(_url, _reason):
        return None

    real_queue = asyncio.Queue

    class _BadQueue:
        def __init__(self):
            self._queue = real_queue()

        async def get(self):
            return await self._queue.get()

        def put_nowait(self, item):
            return self._queue.put_nowait(item)

        async def put(self, item):
            if item is None:
                raise RuntimeError("boom")
            return await self._queue.put(item)

    class _BadTask:
        def __await__(self):
            async def _raise():
                raise RuntimeError("task boom")

            return _raise().__await__()

        def cancel(self):
            return None

    stats = _make_stats()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=_MetaStore(tmp_path),
        stats=stats,
        schedule_interval_hours=1,
        process_url_callback=_process_url,
        acquire_crawler_lock_callback=lambda: asyncio.sleep(0, result="lease"),
    )

    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler", _FakeCrawler)
    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.asyncio.Queue", _BadQueue)
    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.asyncio.create_task", lambda *_args: _BadTask())

    result = await runner.run({"https://example.com/root"})

    assert result
