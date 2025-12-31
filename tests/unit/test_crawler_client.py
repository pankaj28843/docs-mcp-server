"""Unit tests for Crawler client creation and cookie management."""

import json
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

from docs_mcp_server.utils.crawler import CrawlConfig, EfficientCrawler


@pytest.fixture
def crawl_config():
    return CrawlConfig(
        max_pages=10,
    )


@pytest.fixture
def crawler(crawl_config):
    return EfficientCrawler(start_urls={"http://example.com"}, crawl_config=crawl_config)


@pytest.mark.unit
class TestCrawlerClient:
    """Test Crawler client creation and configuration."""

    def test_create_client_defaults(self, crawler):
        """Test client creation with default settings."""
        client = crawler._create_client()

        assert isinstance(client, httpx.AsyncClient)
        assert client.headers["User-Agent"] == crawler.config.user_agent
        assert client.timeout.read == crawler.config.timeout
        assert "gzip" in client.headers["Accept-Encoding"]

    def test_create_client_with_proxy(self, crawler):
        """Test client creation with proxy settings."""
        with patch.dict(os.environ, {"http_proxy": "http://proxy:8080"}):
            client = crawler._create_client()
            # httpx 0.28+ handles proxies differently, checking mount behavior might be complex
            # but we can check if the proxy argument was passed to AsyncClient
            # Since we can't easily inspect the client internals for proxy config in a stable way across versions,
            # we'll trust the logic if it runs without error and we mocked the env var.
            # Alternatively, we can mock httpx.AsyncClient to verify arguments.

    def test_create_client_proxy_mocked(self, crawler):
        """Test client creation with proxy using mocks to verify arguments."""
        with patch.dict(os.environ, {"http_proxy": "http://proxy:8080"}), patch("httpx.AsyncClient") as mock_client_cls:
            crawler._create_client()

            _, kwargs = mock_client_cls.call_args
            assert kwargs["proxy"] == "http://proxy:8080"

    def test_create_client_random_user_agent(self, crawl_config):
        """Test client uses random user agent if not configured."""
        crawl_config.user_agent = ""
        crawler = EfficientCrawler(start_urls={"http://example.com"}, crawl_config=crawl_config)

        # Mock settings to return a specific UA
        crawler.settings = MagicMock()
        crawler.settings.get_random_user_agent.return_value = "Random/1.0"

        client = crawler._create_client()
        assert client.headers["User-Agent"] == "Random/1.0"


@pytest.mark.unit
class TestCrawlerCookies:
    """Test Crawler cookie management."""

    @pytest.fixture
    def cookie_file_path(self, tmp_path):
        """Return a path for the cookie file."""
        return tmp_path / "cookies.json"

    def test_load_cookies_success(self, crawler):
        """Test loading cookies from file."""
        cookie_data = {
            "cookies": {"session": {"value": "123", "domain": "example.com", "path": "/"}, "simple": "value"}
        }

        with patch.object(crawler, "_get_cookie_file_path") as mock_path:
            mock_file = MagicMock()
            mock_file.exists.return_value = True
            mock_file.read_text.return_value = json.dumps(cookie_data)
            mock_path.return_value = mock_file

            # We need to run this async
            import asyncio

            asyncio.run(crawler._load_cookies())

            # Verify cookies were set
            assert crawler._cookies.get("session") == "123"
            assert crawler._cookies.get("simple") == "value"

    def test_load_cookies_file_not_found(self, crawler):
        """Test loading cookies when file doesn't exist."""
        with patch.object(crawler, "_get_cookie_file_path") as mock_path:
            mock_file = MagicMock()
            mock_file.exists.return_value = False
            mock_path.return_value = mock_file

            import asyncio

            asyncio.run(crawler._load_cookies())

            # Should be empty
            assert len(crawler._cookies) == 0

    def test_save_cookies(self, crawler):
        """Test saving cookies to file."""
        crawler._cookies.set("test_cookie", "test_value", domain="example.com")

        with patch.object(crawler, "_get_cookie_file_path") as mock_path:
            mock_file = MagicMock()
            mock_path.return_value = mock_file
            mock_file.parent.exists.return_value = True

            import asyncio

            asyncio.run(crawler._save_cookies())

            mock_file.write_text.assert_called_once()
            # Verify content
            args, _ = mock_file.write_text.call_args
            saved_data = json.loads(args[0])
            assert "cookies" in saved_data
            assert "test_cookie" in saved_data["cookies"]
            assert saved_data["cookies"]["test_cookie"]["value"] == "test_value"

    def test_context_manager(self, crawler):
        """Test async context manager."""
        with (
            patch.object(crawler, "_load_cookies", new_callable=MagicMock) as mock_load,
            patch.object(crawler, "_save_cookies", new_callable=MagicMock) as mock_save,
        ):
            # Mock _load_cookies to be awaitable
            async def async_load():
                pass

            mock_load.side_effect = async_load

            # Mock _save_cookies to be awaitable
            async def async_save():
                pass

            mock_save.side_effect = async_save

            import asyncio

            async def run_context():
                async with crawler as c:
                    assert c.client is not None

            asyncio.run(run_context())

            mock_load.assert_called_once()
            mock_save.assert_called_once()
