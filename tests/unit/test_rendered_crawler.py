"""Behavior tests for browser-backed BFS discovery."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from docs_mcp_server.utils.rendered_crawler import RenderedCrawlConfig, RenderedCrawler


class FakeBrowser:
    def __init__(self, pages: dict[str, tuple[int, str] | Exception]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, str | None]] = []

    async def fetch(self, url, *, user_agent, proxy, timeout_seconds):
        assert user_agent == "agent"
        assert timeout_seconds == 2
        self.calls.append((url, proxy))
        result = self.pages[url]
        if isinstance(result, Exception):
            raise result
        status_code, content = result
        return SimpleNamespace(status_code=status_code, html=content)


def _config(browser, **overrides) -> RenderedCrawlConfig:
    values = {
        "timeout": 2,
        "max_pages": 10,
        "same_host_only": True,
        "allow_querystrings": False,
        "on_url_discovered": None,
        "skip_recently_visited": None,
        "force_crawl": False,
        "markdown_url_suffix": None,
        "user_agent_provider": lambda: "agent",
        "should_process_url": lambda url: "/blocked" not in url,
        "max_concurrency": 2,
        "proxy": None,
        "browser_runtime": browser,
    }
    values.update(overrides)
    return RenderedCrawlConfig(**values)


@pytest.mark.unit
async def test_crawl_is_same_host_bounded_and_reports_discoveries():
    root = "https://docs.example.test/root?ignored=1"
    page = """
    <a href="/one?ignored=1#fragment">one</a>
    <a href="https://outside.test/no">outside</a>
    <a href="/blocked">blocked</a>
    """
    browser = FakeBrowser(
        {
            "https://docs.example.test/root": (200, page),
            "https://docs.example.test/one": (200, '<a href="/two">two</a>'),
        }
    )
    discovered: list[str] = []
    config = _config(browser, max_pages=2, on_url_discovered=discovered.append)

    async with RenderedCrawler({root}, config) as crawler:
        result = await crawler.crawl()

    assert result == {"https://docs.example.test/root", "https://docs.example.test/one"}
    assert discovered[:2] == ["https://docs.example.test/one", "https://docs.example.test/two"]
    assert len(browser.calls) == 2


@pytest.mark.unit
async def test_crawl_skips_recent_pages_and_applies_markdown_suffix():
    root = "https://docs.example.test/root"
    browser = FakeBrowser({})
    config = _config(
        browser,
        skip_recently_visited=lambda url: url == root,
        markdown_url_suffix=".md",
    )

    crawler = RenderedCrawler({root}, config)
    result = await crawler.crawl()

    assert result == {root}
    assert crawler.skipped_count == 1
    assert browser.calls == []


@pytest.mark.unit
async def test_crawl_surfaces_error_when_no_page_succeeds():
    root = "https://docs.example.test/root"
    browser = FakeBrowser({root: ConnectionError("browser unavailable")})

    with pytest.raises(ConnectionError, match="browser unavailable"):
        await RenderedCrawler({root}, _config(browser)).crawl()


@pytest.mark.unit
async def test_crawl_requires_browser_runtime():
    with pytest.raises(RuntimeError, match="shared browser runtime"):
        await RenderedCrawler(
            {"https://docs.example.test/root"},
            _config(None),
        ).crawl()
