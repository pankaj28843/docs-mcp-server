"""Unit tests for crawler edge cases and coverage gaps."""

from collections import deque
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from docs_mcp_server.utils.crawler import (
    AdaptiveRateLimiter,
    CrawlConfig,
    EfficientCrawler,
    HostRateLimitState,
    RateLimitEvent,
)


@pytest.mark.unit
class TestRateLimitLogic:
    """Test detailed rate limiting logic."""

    def test_host_state_success_reduction(self):
        """Test that delay is reduced after 10 consecutive successes."""
        state = HostRateLimitState(host="example.com", base_delay=2.0, current_delay=2.0)

        # Record 9 successes
        for _ in range(9):
            state.record_success()

        assert state.current_delay == 2.0
        assert state.consecutive_successes == 9

        # 10th success should trigger reduction
        state.record_success()
        assert state.current_delay < 2.0
        assert state.current_delay == max(state.min_delay, 2.0 * 0.9)
        assert state.consecutive_successes == 0

    def test_host_state_429_backoff_logic(self):
        """Test various 429 backoff scenarios."""

        def run_scenario(time_diff: float, expected_multiplier: float, consecutive: int = 0):
            state = HostRateLimitState(host="example.com", base_delay=2.0, current_delay=2.0)
            state.consecutive_429s = consecutive
            with patch("time.time", return_value=1000.0):
                state.last_429_time = 1000.0 - time_diff
                state.record_429()
            assert state.current_delay == pytest.approx(2.0 * expected_multiplier)

        # Scenario 1: First 429, standard backoff (1.25x)
        run_scenario(time_diff=100.0, expected_multiplier=1.25)

        # Scenario 2: Rapid 429 (<30s), aggressive backoff (2.0x)
        run_scenario(time_diff=10.0, expected_multiplier=2.0)

        # Scenario 3: Moderate 429 (<60s), moderate backoff (1.5x)
        run_scenario(time_diff=50.0, expected_multiplier=1.5)

        # Scenario 4: Consecutive 429 penalty multiplies the base multiplier by 1.5
        run_scenario(time_diff=100.0, expected_multiplier=1.25 * 1.5, consecutive=2)

    def test_get_recent_429_rate(self):
        """Test calculation of recent 429 rate."""
        state = HostRateLimitState(host="example.com")
        now = time.time()

        # Add some events
        state.events.append(
            RateLimitEvent(timestamp=now - 400, host="example.com", status_code=200, was_success=True)
        )  # Old
        state.events.append(
            RateLimitEvent(timestamp=now - 100, host="example.com", status_code=200, was_success=True)
        )  # Recent success
        state.events.append(
            RateLimitEvent(timestamp=now - 50, host="example.com", status_code=429, was_success=False)
        )  # Recent 429

        # Window is 300s. Should see 2 events, 1 is 429. Rate = 0.5
        assert state.get_recent_429_rate(window_seconds=300) == 0.5

        # Empty events
        state.events.clear()
        assert state.get_recent_429_rate() == 0.0

    def test_adaptive_limiter_stats(self):
        """Test get_stats method."""
        limiter = AdaptiveRateLimiter()
        limiter.record_success("http://example.com/1")
        limiter.record_429("http://example.com/2")

        stats = limiter.get_stats()
        assert "example.com" in stats
        assert stats["example.com"]["total_requests"] == 2
        assert stats["example.com"]["total_429s"] == 1

    @pytest.mark.asyncio
    async def test_rate_limiter_wait_honors_delay(self):
        """Ensure wait sleeps when called faster than adaptive delay allows."""
        limiter = AdaptiveRateLimiter()
        last_request_time = 0.0

        with (
            patch.object(limiter, "get_delay", return_value=1.0),
            patch("docs_mcp_server.utils.crawler.time.time", side_effect=[0.25, 1.25]),
            patch("docs_mcp_server.utils.crawler.asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
        ):
            result = await limiter.wait("http://example.com/page", last_request_time)

        sleep_mock.assert_awaited_once_with(0.75)
        assert result == pytest.approx(1.25)


@pytest.mark.unit
class TestCrawlerEdgeCases:
    """Test crawler edge cases and exception handling."""

    @pytest.mark.asyncio
    async def test_cookie_exceptions(self):
        """Test exception handling in cookie load/save."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})

        # Test load exception
        with patch("pathlib.Path.exists", side_effect=Exception("Disk error")):
            await crawler._load_cookies()  # Should not raise

        # Test save exception
        with patch("pathlib.Path.write_text", side_effect=Exception("Disk error")):
            await crawler._save_cookies()  # Should not raise

    @pytest.mark.asyncio
    async def test_crawl_max_pages_stop(self):
        """Test crawl stopping when max_pages reached."""
        config = CrawlConfig(max_pages=1)
        crawler = EfficientCrawler(start_urls={"http://example.com"}, crawl_config=config)

        # Mock client and process_page to simulate success
        crawler.client = AsyncMock()
        crawler.collected.add("http://example.com")  # Already collected 1

        # Should stop immediately
        async with crawler:
            results = await crawler.crawl()
            assert len(results) == 1

    @pytest.mark.asyncio
    async def test_crawl_requires_client(self):
        """crawl should require the async context manager to set the client."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})

        with pytest.raises(RuntimeError):
            await crawler.crawl()

    @pytest.mark.asyncio
    async def test_crawl_validation_skip_and_logging(self):
        """Exercise crawl loop validation, skip, and error branches."""
        config = CrawlConfig(progress_interval=1)
        crawler = EfficientCrawler(start_urls={"http://example.com/seed"}, crawl_config=config)
        crawler.client = AsyncMock()

        def seed_frontier():
            crawler.frontier.clear()
            crawler.frontier.extend(
                [
                    "http://example.com/seed",
                    "http://example.com/extra",
                    "http://example.com/process",
                ]
            )

        crawler.frontier = deque()
        crawler._initialize_frontier = seed_frontier  # type: ignore[assignment]
        crawler._should_report_progress = Mock(side_effect=[True, False, False])
        crawler._report_progress = Mock()
        crawler._should_crawl_url = Mock(side_effect=[False, True, True])
        crawler.config.skip_recently_visited = Mock(side_effect=[True, False])
        crawler.config.force_crawl = False
        crawler._process_page = AsyncMock(side_effect=Exception("boom"))
        crawler._rate_limiter = Mock()
        crawler._rate_limiter.get_stats.return_value = {
            "example.com": {"total_429s": 2, "total_requests": 3, "current_delay": 1.5}
        }

        with patch("docs_mcp_server.utils.crawler.logger") as mock_logger:
            result = await crawler.crawl()

        assert result == crawler.collected
        assert crawler._crawler_skipped == 1
        crawler._should_report_progress.assert_called()
        crawler._report_progress.assert_called_once()
        assert crawler.config.skip_recently_visited.call_count == 2
        assert any("Rate limit stats for example.com" in call.args[0] for call in mock_logger.info.call_args_list)

    @pytest.mark.asyncio
    async def test_initialize_frontier_filtering(self):
        """Test filtering logic in _initialize_frontier."""
        # Setup URLs that will be filtered
        # 1. Invalid normalization (e.g. ftp)
        # 2. Filtered by should_process_url (e.g. .pdf)
        # 3. Duplicate

        start_urls = {
            "ftp://example.com",  # Invalid scheme
            "http://example.com/doc.pdf",  # Non-HTML
            "http://example.com/page",  # Valid
            "http://example.com/page#frag",  # Duplicate after normalization
        }

        crawler = EfficientCrawler(start_urls=start_urls)
        crawler._initialize_frontier()

        # Should only have http://example.com/page/ (normalized)
        assert len(crawler.frontier) == 1
        assert "http://example.com/page/" in crawler.frontier

    @pytest.mark.asyncio
    async def test_process_page_exceptions(self):
        """Test exception handling in _process_page."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})
        crawler.client = AsyncMock()

        # Mock _fetch_with_httpx_first to return None (failure)
        with patch.object(crawler, "_fetch_with_httpx_first", return_value=None):
            await crawler._process_page("http://example.com")
            assert "http://example.com" not in crawler.collected

    @pytest.mark.asyncio
    async def test_process_page_discovery_callback_error(self):
        """Test exception handling in discovery callback."""
        callback = Mock(side_effect=Exception("Callback failed"))
        config = CrawlConfig(on_url_discovered=callback)
        crawler = EfficientCrawler(start_urls={"http://example.com"}, crawl_config=config)
        crawler.client = AsyncMock()

        # Mock fetch to return HTML with link
        with patch.object(crawler, "_fetch_with_httpx_first", return_value='<a href="/link">Link</a>'):
            await crawler._process_page("http://example.com")

        # Should have called callback, caught exception, and continued
        assert callback.called
        assert "http://example.com/link/" in crawler.frontier

    @pytest.mark.asyncio
    async def test_process_page_referer_and_filters(self):
        """_process_page should honor referer headers and link filtering paths."""

        class SettingsStub:
            def __init__(self):
                self.crawler_playwright_first = True

            def should_process_url(self, url: str) -> bool:
                return not url.endswith(".png")

        crawler = EfficientCrawler(start_urls={"http://example.com"}, settings=SettingsStub())
        crawler.client = AsyncMock()
        crawler._last_url = "http://example.com/previous"
        crawler.visited.add("http://example.com/visited/")
        html = """
        <a href="mailto:spam@example.com">Mail</a>
        <a href="/visited">Visited</a>
        <a href="/image.png">Image</a>
        <a href="/next">Next</a>
        """

        with (
            patch.object(crawler, "_fetch_with_playwright_first", new_callable=AsyncMock) as mock_fetch,
            patch.object(crawler, "_fetch_with_httpx_first", new_callable=AsyncMock) as httpx_mock,
        ):
            mock_fetch.return_value = html
            await crawler._process_page("http://example.com/page")

        assert httpx_mock.await_count == 0
        _, headers = mock_fetch.await_args.args
        assert headers == {"Referer": "http://example.com/previous"}
        assert "http://example.com/page" in crawler.collected
        assert "http://example.com/next/" in crawler.frontier
        assert len(crawler.frontier) == 1

    @pytest.mark.asyncio
    async def test_extract_links_exception(self):
        """Test exception handling in _extract_links."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})

        # Mock BeautifulSoup to raise exception
        with patch("docs_mcp_server.utils.crawler.BeautifulSoup", side_effect=Exception("Parse error")):
            links = crawler._extract_links("<html></html>", "http://example.com")
            assert links == set()

    def test_extract_links_with_list_attributes(self):
        """Link extraction should handle href attributes supplied as lists."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})

        class DummyElement:
            def __getitem__(self, key):
                return ["./docs/guide"]

        dummy = DummyElement()

        with patch("docs_mcp_server.utils.crawler.BeautifulSoup") as mock_bs:
            mock_bs.return_value.find_all.return_value = [dummy]
            links = crawler._extract_links("<html></html>", "http://example.com/base/")

        assert "http://example.com/base/docs/guide" in links

    @pytest.mark.asyncio
    async def test_skip_recently_visited_exception(self):
        """Test exception handling in skip_recently_visited."""
        skipper = Mock(side_effect=Exception("DB Error"))
        config = CrawlConfig(skip_recently_visited=skipper)
        crawler = EfficientCrawler(start_urls={"http://example.com"}, crawl_config=config)
        crawler.client = AsyncMock()

        crawler.frontier.append("http://example.com/page")

        # Should catch exception and proceed to crawl
        with patch.object(crawler, "_process_page") as mock_process:
            async with crawler:
                await crawler.crawl()
                assert mock_process.called

    @pytest.mark.asyncio
    async def test_fetch_httpx_bot_protection_retry(self):
        """Test httpx fetcher retry logic for bot protection (403/404/503)."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})
        crawler.client = AsyncMock()

        # Mock response with 403
        mock_response = Mock()
        mock_response.status_code = 403
        mock_error = Exception("HTTP Error")  # Just to trigger exception path if needed, but we use HTTPStatusError

        # We need to mock httpx.HTTPStatusError
        import httpx

        error = httpx.HTTPStatusError("403 Forbidden", request=Mock(), response=mock_response)

        crawler.client.get.side_effect = error

        # Mock sleep to speed up test
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # Mock Playwright fetcher to succeed eventually
            with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
                mock_fetcher_instance = AsyncMock()
                MockFetcher.return_value.__aenter__.return_value = mock_fetcher_instance
                mock_fetcher_instance.fetch.return_value = ("<html>Success</html>", 200)

                result = await crawler._fetch_with_httpx_first("http://example.com", {})

                assert result == "<html>Success</html>"
                # Should have retried httpx 3 times (0, 1, 2) then switched to Playwright
                assert crawler.client.get.call_count == 3
                assert mock_sleep.call_count >= 2  # Waits between retries

    @pytest.mark.asyncio
    async def test_fetch_httpx_429_exception_path(self):
        """Test httpx fetcher handling 429 raised as exception."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})
        crawler.client = AsyncMock()

        mock_response = Mock()
        mock_response.status_code = 429
        import httpx

        error = httpx.HTTPStatusError("429 Too Many Requests", request=Mock(), response=mock_response)

        # Fail 3 times with 429
        crawler.client.get.side_effect = error

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await crawler._fetch_with_httpx_first("http://example.com", {})
            assert result is None
            assert crawler.client.get.call_count == 3
            assert mock_sleep.call_count >= 2

    @pytest.mark.asyncio
    async def test_log_completion_stats(self):
        """Test _log_completion with skipped pages and rate limit stats."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})
        crawler._crawler_skipped = 5
        crawler.collected = {"http://example.com"}

        # Add some rate limit stats
        crawler._rate_limiter.record_429("http://example.com")

        with patch("docs_mcp_server.utils.crawler.logger") as mock_logger:
            crawler._log_completion(time.time() - 10)

            # Check for skipped message
            args, _ = mock_logger.info.call_args_list[0]
            assert "5 skipped" in args[0]

            # Check for rate limit stats
            args, _ = mock_logger.info.call_args_list[1]
            assert "Rate limit stats for example.com" in args[0]

    @pytest.mark.asyncio
    async def test_apply_rate_limit_with_url(self):
        """_apply_rate_limit should delegate to adaptive limiter when URL provided."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})
        crawler._last_request_time = 0.0
        crawler._rate_limiter.wait = AsyncMock(return_value=9.0)

        await crawler._apply_rate_limit("http://example.com")

        crawler._rate_limiter.wait.assert_awaited_once_with("http://example.com", 0.0)
        assert crawler._last_request_time == 9.0

    @pytest.mark.asyncio
    async def test_apply_rate_limit_without_url(self):
        """Fallback branch should sleep when url not provided but delay enabled."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})
        crawler._last_request_time = 0.0
        crawler.config.delay_seconds = 1.0

        with (
            patch("docs_mcp_server.utils.crawler.time.time", side_effect=[0.25, 1.25]),
            patch("docs_mcp_server.utils.crawler.asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
        ):
            await crawler._apply_rate_limit(None)

        sleep_mock.assert_awaited_once_with(pytest.approx(0.75))
        assert crawler._last_request_time == pytest.approx(1.25)

    def test_should_process_url_respects_settings(self):
        """When settings exist, _should_process_url delegates decisions."""
        fake_settings = Mock()
        fake_settings.should_process_url.return_value = False
        crawler = EfficientCrawler(start_urls={"http://example.com"}, settings=fake_settings)

        result = crawler._should_process_url("http://example.com/page")

        fake_settings.should_process_url.assert_called_once_with("http://example.com/page")
        assert result is False

    def test_should_process_url_blocks_binary_assets(self):
        """Non-HTML file extensions should be filtered out."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})
        assert crawler._should_process_url("http://example.com/doc.pdf") is False

    def test_normalize_url_trailing_slash_and_errors(self):
        """_normalize_url should add trailing slash and swallow parser failures."""
        crawler = EfficientCrawler(start_urls={"http://example.com"})

        normalized = crawler._normalize_url("http://example.com/section")
        assert normalized.endswith("/section/")

        with patch("docs_mcp_server.utils.crawler.urlparse", side_effect=ValueError("boom")):
            assert crawler._normalize_url("http://invalid") is None
