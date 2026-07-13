"""Unit tests for SyncSitemapFetcher proxy probing."""

from types import SimpleNamespace

import httpx
import pytest

from docs_mcp_server.utils.sync_sitemap_fetcher import SyncSitemapFetcher


def _make_settings(proxy_list=None):
    return SimpleNamespace(
        get_proxy_list=lambda: proxy_list or [],
        get_random_user_agent=lambda: "agent",
        should_process_url=lambda url: True,
    )


def _make_fetcher(proxy_list=None):
    async def noop_get(*a, **kw):
        return None

    async def noop_save(*a, **kw):
        pass

    return SyncSitemapFetcher(
        settings=_make_settings(proxy_list),
        get_snapshot_callback=noop_get,
        save_snapshot_callback=noop_save,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_returns_none_when_no_proxies():
    fetcher = _make_fetcher()
    timeout = httpx.Timeout(10.0)
    result = await fetcher._probe_working_proxy(timeout, {}, "https://example.com/sitemap.xml")
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_returns_none_when_no_url():
    fetcher = _make_fetcher(["http://proxy:1"])
    timeout = httpx.Timeout(10.0)
    result = await fetcher._probe_working_proxy(timeout, {}, None)
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_returns_first_working(monkeypatch):
    fetcher = _make_fetcher(["http://bad:1", "http://good:2"])
    timeout = httpx.Timeout(10.0)

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

    monkeypatch.setattr("docs_mcp_server.utils.sync_sitemap_fetcher.httpx.AsyncClient", _FakeClient)
    result = await fetcher._probe_working_proxy(timeout, {}, "https://example.com/sitemap.xml")
    assert result == "http://good:2"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_returns_none_when_all_fail(monkeypatch):
    proxies = [f"http://bad:{port}" for port in (18086, 18085, 8888, 8085)]
    fetcher = _make_fetcher(proxies)
    timeout = httpx.Timeout(10.0)
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

    monkeypatch.setattr("docs_mcp_server.utils.sync_sitemap_fetcher.httpx.AsyncClient", _FailClient)
    result = await fetcher._probe_working_proxy(timeout, {}, "https://example.com/sitemap.xml")
    assert result is None
    assert seen == proxies


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_skips_small_responses(monkeypatch):
    fetcher = _make_fetcher(["http://proxy:1"])
    timeout = httpx.Timeout(10.0)

    class _SmallClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            return SimpleNamespace(status_code=200, content=b"tiny")

    monkeypatch.setattr("docs_mcp_server.utils.sync_sitemap_fetcher.httpx.AsyncClient", _SmallClient)
    result = await fetcher._probe_working_proxy(timeout, {}, "https://example.com/sitemap.xml")
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_probe_rotates_blocked_proxy_then_sticks_to_working(monkeypatch):
    fetcher = _make_fetcher(["http://blocked:1", "http://good:2"])
    timeout = httpx.Timeout(10.0)
    seen: list[str | None] = []

    class _ProbeClient:
        def __init__(self, **kw):
            self.proxy = kw.get("proxy")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            seen.append(self.proxy)
            if self.proxy == "http://blocked:1":
                return SimpleNamespace(status_code=429, content=b"google.com/sorry unusual traffic")
            return SimpleNamespace(status_code=200, content=b"x" * 200)

    monkeypatch.setattr("docs_mcp_server.utils.sync_sitemap_fetcher.httpx.AsyncClient", _ProbeClient)

    result = await fetcher._probe_working_proxy(timeout, {}, "https://example.com/sitemap.xml")

    assert result == "http://good:2"
    assert seen == ["http://blocked:1", "http://good:2"]
    assert fetcher._proxy_pool.candidates() == ["http://good:2", "http://blocked:1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_sitemap_content_rotates_blocked_proxy_then_sticks(monkeypatch):
    fetcher = _make_fetcher(["http://blocked:1", "http://good:2"])
    timeout = httpx.Timeout(10.0)
    seen: list[str | None] = []
    xml = b'<?xml version="1.0"?><urlset></urlset>'

    class _Response:
        def __init__(self, status_code: int, content: bytes) -> None:
            self.status_code = status_code
            self.content = content

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "bad",
                    request=httpx.Request("GET", "https://example.com/sitemap.xml"),
                    response=httpx.Response(self.status_code),
                )

    class _FetchClient:
        def __init__(self, **kw):
            self.proxy = kw.get("proxy")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            seen.append(self.proxy)
            if self.proxy == "http://blocked:1":
                return _Response(429, b"google.com/sorry unusual traffic")
            return _Response(200, xml)

    monkeypatch.setattr("docs_mcp_server.utils.sync_sitemap_fetcher.httpx.AsyncClient", _FetchClient)

    result = await fetcher._fetch_sitemap_content("https://example.com/sitemap.xml", timeout, {})

    assert result == xml
    assert seen == ["http://blocked:1", "http://good:2"]
    assert fetcher._proxy_pool.candidates() == ["http://good:2", "http://blocked:1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_sitemap_content_uses_direct_when_no_proxies(monkeypatch):
    fetcher = _make_fetcher()
    timeout = httpx.Timeout(10.0)
    seen: list[str | None] = []
    xml = b'<?xml version="1.0"?><urlset></urlset>'

    class _DirectClient:
        def __init__(self, **kw):
            self.proxy = kw.get("proxy")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            seen.append(self.proxy)
            return SimpleNamespace(content=xml, raise_for_status=lambda: None)

    monkeypatch.setattr("docs_mcp_server.utils.sync_sitemap_fetcher.httpx.AsyncClient", _DirectClient)

    result = await fetcher._fetch_sitemap_content("https://example.com/sitemap.xml", timeout, {})

    assert result == xml
    assert seen == [None]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_sitemap_content_returns_none_after_exhausting_proxy_failures(monkeypatch):
    proxies = [f"http://bad:{port}" for port in (18086, 18085, 8888, 8085)]
    fetcher = _make_fetcher(proxies)
    timeout = httpx.Timeout(10.0)
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

    monkeypatch.setattr("docs_mcp_server.utils.sync_sitemap_fetcher.httpx.AsyncClient", _FailClient)

    result = await fetcher._fetch_sitemap_content("https://example.com/sitemap.xml", timeout, {})

    assert result is None
    assert seen == proxies


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_continues_after_generic_sitemap_processing_error(monkeypatch):
    def _raise(_url: str) -> bool:
        raise RuntimeError("filter failed")

    saved: list[tuple[str | None, dict]] = []

    async def get_snapshot(*a, **kw):
        return None

    async def save_snapshot(payload, key=None):
        saved.append((key, payload))

    fetcher = SyncSitemapFetcher(
        settings=SimpleNamespace(
            get_proxy_list=list,
            get_random_user_agent=lambda: "agent",
            should_process_url=_raise,
        ),
        get_snapshot_callback=get_snapshot,
        save_snapshot_callback=save_snapshot,
    )
    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://example.com/docs/page</loc></url>"
        b"</urlset>"
    )

    async def _fetch_content(*a, **kw):
        return xml

    monkeypatch.setattr(fetcher, "_fetch_sitemap_content", _fetch_content)

    changed, entries = await fetcher.fetch(["https://example.com/sitemap.xml"])

    assert changed is False
    assert entries == []
    assert saved[-1][0] is None
