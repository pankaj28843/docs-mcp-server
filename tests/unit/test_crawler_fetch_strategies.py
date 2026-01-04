"""Unit tests for crawler fetch strategies (Playwright vs httpx)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from docs_mcp_server.utils.crawler import CrawlConfig, EfficientCrawler


@pytest.fixture
def crawler():
    config = CrawlConfig(
        max_pages=10,
        # max_depth removed
        # allowed_hosts removed (derived from start_urls)
        # playwright_first removed (in settings)
    )
    settings = MagicMock()
    settings.crawler_playwright_first = False

    crawler = EfficientCrawler(start_urls={"http://example.com"}, crawl_config=config, settings=settings)
    crawler.client = AsyncMock(spec=httpx.AsyncClient)
    # Initialize rate limiter manually since we mocked client creation
    from docs_mcp_server.utils.crawler import AdaptiveRateLimiter

    crawler._rate_limiter = AdaptiveRateLimiter()
    return crawler


@pytest.mark.unit
@pytest.mark.asyncio
class TestFetchWithPlaywrightFirst:
    """Tests for _fetch_with_playwright_first strategy."""

    @pytest.fixture
    def pw_crawler(self, crawler):
        crawler.settings.crawler_playwright_first = True
        return crawler

    async def test_playwright_success(self, pw_crawler):
        """Test successful fetch with Playwright."""
        with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
            mock_instance = AsyncMock()
            MockFetcher.return_value.__aenter__.return_value = mock_instance
            mock_instance.fetch.return_value = ("<html>content</html>", 200)

            content = await pw_crawler._fetch_with_playwright_first("http://example.com", {})

            assert content == "<html>content</html>"
            mock_instance.fetch.assert_called_once_with("http://example.com")
            pw_crawler.client.get.assert_not_called()

    async def test_playwright_429_backoff(self, pw_crawler):
        """Test Playwright receiving 429 triggers backoff."""
        with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
            mock_instance = AsyncMock()
            MockFetcher.return_value.__aenter__.return_value = mock_instance
            mock_instance.fetch.return_value = ("", 429)

            # Mock sleep to avoid waiting
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                content = await pw_crawler._fetch_with_playwright_first("http://example.com", {})

                assert content is None
                mock_sleep.assert_called_once()
                # Should record 429
                assert "example.com" in pw_crawler._rate_limiter._host_states
                assert pw_crawler._rate_limiter._host_states["example.com"].consecutive_429s > 0

    async def test_playwright_error_fallback_to_httpx_success(self, pw_crawler):
        """Test Playwright failure falls back to httpx."""
        with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
            MockFetcher.side_effect = Exception("Playwright crashed")

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "<html>httpx content</html>"
            pw_crawler.client.get.return_value = mock_response

            content = await pw_crawler._fetch_with_playwright_first("http://example.com", {})

            assert content == "<html>httpx content</html>"
            pw_crawler.client.get.assert_called_once()

    async def test_playwright_oserror_emfile_backoff(self, pw_crawler):
        """Test Playwright OSError (EMFILE) triggers backoff."""
        with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
            os_error = OSError()
            os_error.errno = 24  # EMFILE
            MockFetcher.side_effect = os_error

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                content = await pw_crawler._fetch_with_playwright_first("http://example.com", {})

                assert content is None
                mock_sleep.assert_called_with(30)
                pw_crawler.client.get.assert_not_called()

    async def test_httpx_fallback_429(self, pw_crawler):
        """Test httpx fallback receiving 429."""
        with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
            MockFetcher.side_effect = Exception("Playwright failed")

            mock_response = MagicMock()
            mock_response.status_code = 429
            pw_crawler.client.get.return_value = mock_response

            # _fetch_with_playwright_first uses include_rate_limit internally
            # so it returns tuple by default now
            result = await pw_crawler._fetch_with_playwright_first("http://example.com", {})

            # Result could be None or (None, True) depending on include_rate_limit flag
            # The function defaults to include_rate_limit=False, so returns just None
            # But httpx fallback path uses format_result which respects the flag
            if isinstance(result, tuple):
                content, rate_limited = result
                assert content is None
                assert rate_limited is True
            else:
                assert result is None

            assert "example.com" in pw_crawler._rate_limiter._host_states
            assert pw_crawler._rate_limiter._host_states["example.com"].consecutive_429s > 0

    async def test_httpx_fallback_error(self, pw_crawler):
        """Test httpx fallback raising exception."""
        with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
            MockFetcher.side_effect = Exception("Playwright failed")

            pw_crawler.client.get.side_effect = httpx.RequestError("Network error")

            content = await pw_crawler._fetch_with_playwright_first("http://example.com", {})

            assert content is None

    async def test_playwright_oserror_non_emfile_falls_back_to_httpx(self, pw_crawler):
        """Non-EMFILE OSError should fall back to httpx and succeed."""
        with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
            os_error = OSError()
            os_error.errno = 1
            MockFetcher.side_effect = os_error

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "<html>fallback</html>"
            pw_crawler.client.get.return_value = mock_response

            content = await pw_crawler._fetch_with_playwright_first("http://example.com", {})

            assert content == "<html>fallback</html>"
            pw_crawler.client.get.assert_called_once()

    async def test_httpx_fallback_http_status_error(self, pw_crawler):
        """HTTPStatusError from httpx fallback should log and return None."""
        with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
            MockFetcher.side_effect = Exception("Playwright failed")

            mock_response = MagicMock()
            mock_response.status_code = 500
            error = httpx.HTTPStatusError("boom", request=MagicMock(), response=MagicMock(status_code=500))
            mock_response.raise_for_status.side_effect = error
            pw_crawler.client.get.return_value = mock_response

            content = await pw_crawler._fetch_with_playwright_first("http://example.com", {})

            assert content is None


@pytest.mark.unit
@pytest.mark.asyncio
class TestFetchWithHttpxFirst:
    """Tests for _fetch_with_httpx_first strategy."""

    async def test_httpx_success(self, crawler):
        """Test successful fetch with httpx."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>content</html>"
        crawler.client.get.return_value = mock_response

        content = await crawler._fetch_with_httpx_first("http://example.com", {})

        assert content == "<html>content</html>"
        crawler.client.get.assert_called_once()

    async def test_httpx_429_retry_backoff(self, crawler):
        """Test httpx 429 triggers retry with backoff."""
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.text = "<html>content</html>"

        crawler.client.get.side_effect = [mock_response_429, mock_response_200]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            content = await crawler._fetch_with_httpx_first("http://example.com", {})

            assert content == "<html>content</html>"
            assert crawler.client.get.call_count == 2
            mock_sleep.assert_called_once()

    async def test_httpx_bot_protection_fallback_to_playwright(self, crawler):
        """Test httpx 403 triggers fallback to Playwright after retries."""
        # Simulate 403 (Forbidden/Bot protection)
        error_403 = httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=MagicMock(status_code=403))

        crawler.client.get.side_effect = error_403

        with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
            mock_instance = AsyncMock()
            MockFetcher.return_value.__aenter__.return_value = mock_instance
            mock_instance.fetch.return_value = ("<html>pw content</html>", 200)

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                content = await crawler._fetch_with_httpx_first("http://example.com", {})

                assert content == "<html>pw content</html>"
                # Should have retried httpx a few times before fallback
                assert crawler.client.get.call_count == 3
                mock_instance.fetch.assert_called_once()

    async def test_httpx_fallback_playwright_failure(self, crawler):
        """Test fallback to Playwright also failing."""
        error_403 = httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=MagicMock(status_code=403))
        crawler.client.get.side_effect = error_403

        with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
            MockFetcher.side_effect = Exception("Playwright failed")

            with patch("asyncio.sleep", new_callable=AsyncMock):
                content = await crawler._fetch_with_httpx_first("http://example.com", {})

                assert content is None

    async def test_httpx_fallback_playwright_oserror(self, crawler):
        """Test fallback to Playwright failing with OSError."""
        error_403 = httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=MagicMock(status_code=403))
        crawler.client.get.side_effect = error_403

        with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
            os_error = OSError()
            os_error.errno = 24
            MockFetcher.side_effect = os_error

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                content = await crawler._fetch_with_httpx_first("http://example.com", {})

                assert content is None
                # Should sleep 30s for EMFILE
                mock_sleep.assert_called_with(30)
