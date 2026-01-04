"""Unit tests for PlaywrightFetcher internals without launching a browser."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from article_extractor import PlaywrightFetcher
import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_storage_state_clears_context_and_disk(tmp_path):
    """clear_storage_state should flush cookies, localStorage, and disk cache."""
    fetcher = PlaywrightFetcher()
    context = AsyncMock()
    page_one = AsyncMock()
    page_two = AsyncMock()
    context.pages = [page_one, page_two]
    fetcher._context = context

    storage_file = tmp_path / "state.json"
    storage_file.write_text("data", encoding="utf-8")
    fetcher._storage_state_override = storage_file

    await fetcher.clear_storage_state()

    context.clear_cookies.assert_awaited_once()
    assert page_one.evaluate.await_count == 1
    assert page_two.evaluate.await_count == 1
    assert storage_file.exists() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_cookies_only_touches_cookies(tmp_path):
    """clear_cookies should not try to manipulate localStorage."""
    fetcher = PlaywrightFetcher()

    class CookieContext:
        def __init__(self):
            self.clear_cookies = AsyncMock()

    fetcher._context = CookieContext()
    storage_file = tmp_path / "cookies.json"
    storage_file.write_text("cookies", encoding="utf-8")
    fetcher._storage_state_override = storage_file

    await fetcher.clear_cookies()

    fetcher._context.clear_cookies.assert_awaited_once()
    # clear_cookies does NOT delete the file
    # (only clear_storage_state removes the file)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_waits_for_selector_and_stability(monkeypatch):
    """Fetch should wait for selectors, enforce stability, and return status."""
    fetcher = PlaywrightFetcher()
    fetcher._semaphore = asyncio.Semaphore(1)
    context = AsyncMock()
    fetcher._context = context
    page = AsyncMock()
    context.new_page.return_value = page
    page.goto.return_value = SimpleNamespace(status=202)
    page.content = AsyncMock(side_effect=["first", "first"])
    monkeypatch.setattr(asyncio, "sleep", AsyncMock(return_value=None))

    content, status = await fetcher.fetch("https://example.com", wait_for_selector="#app")

    assert status == 202
    assert content == "first"
    page.wait_for_selector.assert_awaited_once()
    assert page.content.await_count == 2  # stability loop ran twice
    page.close.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_handles_selector_timeout(monkeypatch, caplog):
    """Timeouts from wait_for_selector should return HTTP 408 with fallback HTML."""
    fetcher = PlaywrightFetcher()
    fetcher._semaphore = asyncio.Semaphore(1)
    context = AsyncMock()
    fetcher._context = context
    page = AsyncMock()
    context.new_page.return_value = page
    page.goto.return_value = SimpleNamespace(status=None)
    page.wait_for_selector.side_effect = asyncio.TimeoutError
    page.content = AsyncMock(return_value="<html>fallback</html>")

    caplog.set_level("WARNING")
    content, status = await fetcher.fetch("https://example.com", wait_for_selector="#slow")

    assert status == 408
    assert content == "<html>fallback</html>"
    assert any("Timed out waiting for selector" in message for message in caplog.messages)
    page.close.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_without_context_raises():
    """Fetch without initializing context should raise RuntimeError."""
    fetcher = PlaywrightFetcher()
    # _context is None by default

    with pytest.raises(RuntimeError, match="not initialized"):
        await fetcher.fetch("https://example.com")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fetch_without_wait_for_stability(monkeypatch):
    """Fetch with wait_for_stability=False should return content immediately."""
    fetcher = PlaywrightFetcher()
    fetcher._semaphore = asyncio.Semaphore(1)
    context = AsyncMock()
    fetcher._context = context
    page = AsyncMock()
    context.new_page.return_value = page
    page.goto.return_value = SimpleNamespace(status=200)
    page.content = AsyncMock(return_value="<html>immediate</html>")

    content, status = await fetcher.fetch("https://example.com", wait_for_stability=False)

    assert status == 200
    assert content == "<html>immediate</html>"
    # Only called once (no stability loop)
    page.content.assert_awaited_once()
    page.close.assert_awaited_once()


@pytest.mark.unit
def test_fetcher_init_defaults():
    """PlaywrightFetcher should have sensible defaults."""
    fetcher = PlaywrightFetcher()
    assert fetcher.headless is True
    assert fetcher.timeout == 30000
    assert fetcher._playwright is None
    assert fetcher._browser is None
    assert fetcher._context is None
    assert fetcher._semaphore is None


@pytest.mark.unit
def test_fetcher_init_custom_values():
    """PlaywrightFetcher should accept custom headless and timeout."""
    fetcher = PlaywrightFetcher(headless=False, timeout=60000)
    assert fetcher.headless is False
    assert fetcher.timeout == 60000
