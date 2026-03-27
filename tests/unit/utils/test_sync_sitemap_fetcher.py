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
    fetcher = _make_fetcher(["http://bad:1"])
    timeout = httpx.Timeout(10.0)

    class _FailClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            raise ConnectionError("refused")

    monkeypatch.setattr("docs_mcp_server.utils.sync_sitemap_fetcher.httpx.AsyncClient", _FailClient)
    result = await fetcher._probe_working_proxy(timeout, {}, "https://example.com/sitemap.xml")
    assert result is None


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
