"""Unit tests for SyncDiscoveryRunner edge cases."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

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


class _FakeAndroidCrawler(_FakeCrawler):
    async def crawl(self):
        discovered = {
            "https://developer.android.com/ndk/guides/concepts?hl=en",
            "https://developer.android.com/ndk/guides/build.md.txt?hl=en",
            "https://developer.android.com/ndk/guides/this%20also%20helps%0Akeep%20details",
            "https://developer.android.com/ndk/guides/image.png",
        }
        for url in discovered:
            if self._crawl_config.on_url_discovered:
                self._crawl_config.on_url_discovered(url)
        return set(self._root_urls) | discovered


def _make_settings():
    return SimpleNamespace(
        max_crawl_pages=10,
        markdown_url_suffix="",
        canonicalize_discovered_markdown_urls=False,
        preserve_query_strings=True,
        crawler_playwright_first=False,
        get_random_user_agent=lambda: "agent",
        should_process_url=lambda url: True,
        crawler_min_concurrency=1,
        crawler_max_concurrency=2,
        crawler_max_sessions=2,
        crawler_proxy_attempt_timeout_seconds=1,
        get_proxy_list=list,
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
    def __init__(self):
        self.events: list[dict] = []
        self.queue: set[str] = set()
        self.released: list[str] = []

    async def release_lock(self, lease):
        self.released.append(lease)

    async def record_event(self, *, url, event_type, status, reason=None, detail=None, duration_ms=None):
        self.events.append(
            {
                "url": url,
                "event_type": event_type,
                "status": status,
                "reason": reason,
                "detail": detail,
                "duration_ms": duration_ms,
            }
        )

    async def enqueue_urls(self, urls, *, reason=None, priority=0):
        for url in urls:
            self.queue.add(url)

    def was_recently_fetched_sync(self, url: str, *, interval_hours: float) -> bool:
        return False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_handles_progressive_processor_error(monkeypatch):
    async def _process_url(_url, _reason):
        raise RuntimeError("boom")

    stats = _make_stats()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=_MetaStore(),
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
async def test_run_handles_queueing_failure(monkeypatch):
    async def _process_url(_url, _reason):
        return None

    def _raise(*_args, **_kwargs):
        raise RuntimeError("queue boom")

    stats = _make_stats()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=_MetaStore(),
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
async def test_run_handles_recently_visited_parse_error(monkeypatch):
    async def _process_url(_url, _reason):
        return None

    stats = _make_stats()
    store = _MetaStore()

    def _raise(*_args, **_kwargs):
        raise ValueError("bad")

    monkeypatch.setattr(store, "was_recently_fetched_sync", _raise)
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=store,
        stats=stats,
        schedule_interval_hours=1,
        process_url_callback=_process_url,
        acquire_crawler_lock_callback=lambda: asyncio.sleep(0, result="lease"),
    )

    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler", _FakeCrawler)

    result = await runner.run({"https://example.com/root"})

    assert result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_records_progressive_batch(monkeypatch):
    async def _process_url(_url, _reason):
        return None

    stats = _make_stats()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=_MetaStore(),
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
async def test_run_handles_recently_visited_failure_status(monkeypatch):
    async def _process_url(_url, _reason):
        return None

    url = "https://example.com/discovered"
    stats = _make_stats()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=_make_settings(),
        metadata_store=_MetaStore(),
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
async def test_run_handles_progressive_timeout(monkeypatch):
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
        metadata_store=_MetaStore(),
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
async def test_run_handles_queue_put_and_task_failure(monkeypatch):
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
        metadata_store=_MetaStore(),
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_working_proxy_no_proxies():
    runner = SyncDiscoveryRunner(
        tenant_codename="t",
        settings=_make_settings(),
        metadata_store=_MetaStore(),
        stats=_make_stats(),
        schedule_interval_hours=24,
        process_url_callback=AsyncMock(),
        acquire_crawler_lock_callback=AsyncMock(return_value="l"),
    )
    assert await runner._probe_working_proxy({"https://example.com"}) is None
    assert await runner._probe_working_proxy(set()) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_working_proxy_returns_first_working(monkeypatch):
    settings = _make_settings()
    settings.get_proxy_list = lambda: ["http://bad:1", "http://good:2"]
    runner = SyncDiscoveryRunner(
        tenant_codename="t",
        settings=settings,
        metadata_store=_MetaStore(),
        stats=_make_stats(),
        schedule_interval_hours=24,
        process_url_callback=AsyncMock(),
        acquire_crawler_lock_callback=AsyncMock(return_value="l"),
    )

    class _FakeClient:
        def __init__(self, **kw):
            self.proxy = kw.get("proxy")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            if self.proxy == "http://bad:1":
                raise ConnectionError("refused")
            return SimpleNamespace(status_code=200, content=b"x" * 200)

    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.httpx.AsyncClient", _FakeClient)
    assert await runner._probe_working_proxy({"https://example.com"}) == "http://good:2"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_working_proxy_skips_blocked_response(monkeypatch):
    settings = _make_settings()
    settings.get_proxy_list = lambda: ["http://blocked:1", "http://good:2"]
    runner = SyncDiscoveryRunner(
        tenant_codename="t",
        settings=settings,
        metadata_store=_MetaStore(),
        stats=_make_stats(),
        schedule_interval_hours=24,
        process_url_callback=AsyncMock(),
        acquire_crawler_lock_callback=AsyncMock(return_value="l"),
    )

    class _FakeClient:
        def __init__(self, **kw):
            self.proxy = kw.get("proxy")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            if self.proxy == "http://blocked:1":
                return SimpleNamespace(status_code=429, content=b"google.com/sorry unusual traffic" * 10)
            return SimpleNamespace(status_code=200, content=b"x" * 200)

    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.httpx.AsyncClient", _FakeClient)
    assert await runner._probe_working_proxy({"https://example.com"}) == "http://good:2"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_working_proxy_all_fail(monkeypatch):
    settings = _make_settings()
    proxies = [f"http://bad:{port}" for port in (18086, 18085, 8888, 8085)]
    settings.get_proxy_list = lambda: proxies
    runner = SyncDiscoveryRunner(
        tenant_codename="t",
        settings=settings,
        metadata_store=_MetaStore(),
        stats=_make_stats(),
        schedule_interval_hours=24,
        process_url_callback=AsyncMock(),
        acquire_crawler_lock_callback=AsyncMock(return_value="l"),
    )
    seen: list[str | None] = []

    class _FailClient:
        def __init__(self, **kw):
            self.proxy = kw.get("proxy")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            seen.append(self.proxy)
            raise ConnectionError("refused")

    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.httpx.AsyncClient", _FailClient)
    assert await runner._probe_working_proxy({"https://example.com"}) is None
    assert seen == proxies


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_rotates_crawler_proxy_after_attempt_failure(monkeypatch):
    async def _process_url(_url, _reason):
        return None

    settings = _make_settings()
    settings.get_proxy_list = lambda: ["http://blocked:1", "http://good:2"]
    store = _MetaStore()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=settings,
        metadata_store=store,
        stats=_make_stats(),
        schedule_interval_hours=1,
        process_url_callback=_process_url,
        acquire_crawler_lock_callback=lambda: asyncio.sleep(0, result="lease"),
    )
    attempts: list[str | None] = []

    class _ProxyCrawler(_FakeCrawler):
        async def crawl(self):
            proxy = self._crawl_config.network.proxy if self._crawl_config.network else None
            attempts.append(proxy)
            if proxy == "http://blocked:1":
                raise asyncio.TimeoutError
            url = "https://example.com/proxy-good"
            if self._crawl_config.on_url_discovered:
                self._crawl_config.on_url_discovered(url)
            return set(self._root_urls) | {url}

    monkeypatch.setattr(runner, "_probe_proxy", AsyncMock(return_value=True))
    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler", _ProxyCrawler)

    result = await runner.run({"https://example.com/root"})

    assert attempts == ["http://blocked:1", "http://good:2"]
    assert result == {"https://example.com/proxy-good"}
    assert store.released == ["lease"]
    assert any(event["event_type"] == "crawl_proxy_failed" for event in store.events)
    assert any(
        event["event_type"] == "crawl_complete" and event["detail"]["proxy"] == "http://good:2"
        for event in store.events
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_skips_when_all_crawler_proxy_attempts_fail(monkeypatch):
    async def _process_url(_url, _reason):
        return None

    settings = _make_settings()
    proxies = [f"http://bad:{port}" for port in (18086, 18085, 8888, 8085)]
    settings.get_proxy_list = lambda: proxies
    store = _MetaStore()
    runner = SyncDiscoveryRunner(
        tenant_codename="tenant",
        settings=settings,
        metadata_store=store,
        stats=_make_stats(),
        schedule_interval_hours=1,
        process_url_callback=_process_url,
        acquire_crawler_lock_callback=lambda: asyncio.sleep(0, result="lease"),
    )
    attempts: list[str | None] = []

    class _FailingProxyCrawler(_FakeCrawler):
        async def crawl(self):
            proxy = self._crawl_config.network.proxy if self._crawl_config.network else None
            attempts.append(proxy)
            raise RuntimeError("blocked")

    monkeypatch.setattr(runner, "_probe_proxy", AsyncMock(return_value=True))
    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler", _FailingProxyCrawler)

    result = await runner.run({"https://example.com/root"})

    assert result == set()
    assert attempts == proxies
    assert store.released == ["lease"]
    assert any(
        event["event_type"] == "crawl_skipped" and event["reason"] == "all_proxy_attempts_failed"
        for event in store.events
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_canonicalizes_android_markdown_mirror_discoveries(monkeypatch):
    processed: list[str] = []

    async def _process_url(url, _reason):
        processed.append(url)

    settings = _make_settings()
    settings.markdown_url_suffix = ".md.txt"
    settings.canonicalize_discovered_markdown_urls = True
    settings.preserve_query_strings = False
    settings.should_process_url = lambda url: url.startswith("https://developer.android.com/ndk/guides")

    store = _MetaStore()
    runner = SyncDiscoveryRunner(
        tenant_codename="android-ndk",
        settings=settings,
        metadata_store=store,
        stats=_make_stats(),
        schedule_interval_hours=1,
        process_url_callback=_process_url,
        acquire_crawler_lock_callback=lambda: asyncio.sleep(0, result="lease"),
    )

    monkeypatch.setattr("docs_mcp_server.utils.sync_discovery_runner.EfficientCrawler", _FakeAndroidCrawler)
    monkeypatch.setattr(
        "docs_mcp_server.utils.sync_discovery_runner.asyncio.get_event_loop",
        lambda: SimpleNamespace(
            call_soon_threadsafe=lambda fn, arg: fn(arg),
            create_task=asyncio.create_task,
        ),
    )

    result = await runner.run({"https://developer.android.com/ndk/guides?hl=en"})

    assert result == {
        "https://developer.android.com/ndk/guides/build.md.txt",
        "https://developer.android.com/ndk/guides/concepts.md.txt",
    }
    assert set(processed) == result
    assert store.queue == result
