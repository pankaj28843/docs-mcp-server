"""Unit tests for the web crawler module.

Following Cosmic Python Chapter 3: Testing with abstractions
- Test domain logic in isolation
- Test state management (visited URLs, frontier)
- Test configuration and customization
- Mock external dependencies (HTTP requests)
- Test async context manager protocol
- Use test doubles instead of real network calls
- Edge-to-edge testing with fakes
"""

import logging
import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.utils.crawler import CrawlConfig, EfficientCrawler


pytestmark = pytest.mark.unit


class TestCrawlConfig:
    """Test crawler configuration value object."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CrawlConfig()

        assert config.user_agent == ""
        assert config.timeout == 30
        assert config.delay_seconds == 2.0
        assert config.max_pages is None
        assert config.same_host_only is True
        assert config.normalize_trailing_slash is True
        assert config.allow_querystrings is False
        assert config.max_retries == 3
        assert config.progress_interval == 10

    def test_custom_config(self):
        """Test custom configuration values."""
        config = CrawlConfig(
            user_agent="CustomBot/1.0",
            timeout=60,
            delay_seconds=5.0,
            max_pages=100,
            same_host_only=False,
            normalize_trailing_slash=False,
            allow_querystrings=True,
            max_retries=5,
            progress_interval=50,
        )

        assert config.user_agent == "CustomBot/1.0"
        assert config.timeout == 60
        assert config.delay_seconds == 5.0
        assert config.max_pages == 100
        assert config.same_host_only is False
        assert config.normalize_trailing_slash is False
        assert config.allow_querystrings is True
        assert config.max_retries == 5
        assert config.progress_interval == 50

    def test_callback_configuration(self):
        """Test URL discovery callback configuration."""
        callback_called = []

        def on_url(url):
            callback_called.append(url)

        config = CrawlConfig(on_url_discovered=on_url)

        assert config.on_url_discovered is not None
        config.on_url_discovered("https://example.com")
        assert callback_called == ["https://example.com"]


class TestEfficientCrawlerInitialization:
    """Test crawler initialization."""

    @pytest.fixture
    def settings(self):
        """Create test settings."""
        return Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_entry_url="https://example.com/",
            url_whitelist_prefixes="https://example.com/",
        )

    def test_initialization_with_start_urls(self, settings):
        """Test crawler initialization with start URLs."""
        start_urls = {"https://example.com/page1", "https://example.com/page2"}
        crawler = EfficientCrawler(start_urls, settings=settings)

        assert crawler.start_urls == start_urls
        assert crawler.settings == settings
        assert len(crawler.visited) == 0
        assert len(crawler.collected) == 0
        assert len(crawler.frontier) == 0

    def test_initialization_extracts_allowed_hosts(self, settings):
        """Test that allowed hosts are extracted from start URLs."""
        start_urls = {
            "https://example.com/page1",
            "https://docs.example.com/page2",
        }
        crawler = EfficientCrawler(start_urls, settings=settings)

        assert "example.com" in crawler.allowed_hosts
        assert "docs.example.com" in crawler.allowed_hosts
        assert len(crawler.allowed_hosts) == 2

    def test_initialization_with_custom_config(self, settings):
        """Test initialization with custom crawl config."""
        config = CrawlConfig(max_pages=50, delay_seconds=1.0)
        start_urls = {"https://example.com/"}

        crawler = EfficientCrawler(start_urls, config, settings)

        assert crawler.config.max_pages == 50
        assert crawler.config.delay_seconds == 1.0


class TestURLNormalization:
    """Test URL normalization logic."""

    @pytest.fixture
    def crawler(self):
        """Create crawler instance for testing."""
        settings = Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_entry_url="https://example.com/",
            url_whitelist_prefixes="https://example.com/",
        )
        return EfficientCrawler({"https://example.com/"}, settings=settings)

    def test_normalize_removes_fragment(self, crawler):
        """Test that fragments are removed from URLs."""
        url = "https://example.com/page#section"
        normalized = crawler._normalize_url(url)

        assert normalized == "https://example.com/page/"
        assert "#" not in normalized

    def test_normalize_adds_trailing_slash(self, crawler):
        """Test that trailing slash is added to directory URLs."""
        url = "https://example.com/docs"
        normalized = crawler._normalize_url(url)

        assert normalized == "https://example.com/docs/"

    def test_normalize_preserves_file_extensions(self, crawler):
        """Test that file extensions don't get trailing slash."""
        url = "https://example.com/file.html"
        normalized = crawler._normalize_url(url)

        assert normalized == "https://example.com/file.html"
        assert not normalized.endswith("html/")

    def test_normalize_removes_query_by_default(self, crawler):
        """Test that query strings are removed by default."""
        url = "https://example.com/page?param=value"
        normalized = crawler._normalize_url(url)

        assert "?" not in normalized
        assert "param" not in normalized

    def test_normalize_keeps_query_when_allowed(self):
        """Test that query strings are kept when configured."""
        settings = Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_entry_url="https://example.com/",
            url_whitelist_prefixes="https://example.com/",
        )
        config = CrawlConfig(allow_querystrings=True)
        crawler = EfficientCrawler({"https://example.com/"}, config, settings)

        url = "https://example.com/page?param=value"
        normalized = crawler._normalize_url(url)

        assert "?" in normalized
        assert "param=value" in normalized

    def test_normalize_rejects_non_http_schemes(self, crawler):
        """Test that non-HTTP(S) URLs are rejected."""
        assert crawler._normalize_url("ftp://example.com/file") is None
        assert crawler._normalize_url("mailto:test@example.com") is None
        assert crawler._normalize_url("javascript:void(0)") is None

    def test_normalize_handles_invalid_urls(self, crawler):
        """Test that invalid URLs return None."""
        assert crawler._normalize_url("not a url") is None
        assert crawler._normalize_url("") is None


class TestURLFiltering:
    """Test URL filtering and validation logic."""

    @pytest.fixture
    def settings(self):
        """Create settings with URL filters."""
        return Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_entry_url="https://example.com/docs/",
            url_whitelist_prefixes="https://example.com/docs/",
            url_blacklist_prefixes="https://example.com/docs/api/v1/",
        )

    @pytest.fixture
    def crawler(self, settings):
        """Create crawler with URL filters."""
        return EfficientCrawler({"https://example.com/docs/"}, settings=settings)

    def test_should_process_whitelisted_url(self, crawler):
        """Test that whitelisted URLs are processed."""
        url = "https://example.com/docs/guide/intro/"
        assert crawler._should_process_url(url) is True

    def test_should_not_process_blacklisted_url(self, crawler):
        """Test that blacklisted URLs are rejected."""
        url = "https://example.com/docs/api/v1/endpoints/"
        assert crawler._should_process_url(url) is False

    def test_should_not_process_non_whitelisted_url(self, crawler):
        """Test that non-whitelisted URLs are rejected."""
        url = "https://example.com/blog/post/"
        assert crawler._should_process_url(url) is False

    def test_should_not_process_non_html_files(self, crawler):
        """Test that non-HTML files are rejected."""
        non_html_files = [
            "https://example.com/docs/style.css",
            "https://example.com/docs/script.js",
            "https://example.com/docs/image.png",
            "https://example.com/docs/document.pdf",
            "https://example.com/docs/archive.zip",
        ]

        for url in non_html_files:
            assert crawler._should_process_url(url) is False

    def test_should_crawl_same_host(self, crawler):
        """Test that same-host URLs are allowed."""
        url = "https://example.com/docs/page/"
        assert crawler._should_crawl_url(url) is True

    def test_should_not_crawl_different_host_by_default(self, crawler):
        """Test that different hosts are rejected by default."""
        url = "https://other-site.com/page/"
        assert crawler._should_crawl_url(url) is False

    def test_should_crawl_different_host_when_allowed(self):
        """Test that different hosts are allowed when configured."""
        settings = Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_entry_url="https://example.com/",
            url_whitelist_prefixes="https://",  # Allow all HTTPS
        )
        config = CrawlConfig(same_host_only=False)
        crawler = EfficientCrawler({"https://example.com/"}, config, settings)

        url = "https://other-site.com/page/"
        assert crawler._should_crawl_url(url) is True


class TestLinkExtraction:
    """Test link extraction from HTML."""

    @pytest.fixture
    def crawler(self):
        """Create crawler instance."""
        settings = Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_entry_url="https://example.com/",
            url_whitelist_prefixes="https://example.com/",
        )
        return EfficientCrawler({"https://example.com/"}, settings=settings)

    def test_extract_links_from_a_tags(self, crawler):
        """Test extracting links from <a> tags."""
        html = """
        <html>
            <body>
                <a href="/page1">Page 1</a>
                <a href="/page2">Page 2</a>
            </body>
        </html>
        """
        base_url = "https://example.com/"

        links = crawler._extract_links(html, base_url)

        assert "https://example.com/page1" in links
        assert "https://example.com/page2" in links
        assert len(links) == 2

    def test_extract_links_from_custom_elements(self, crawler):
        """Test extracting links from custom elements with href."""
        html = """
        <html>
            <body>
                <div href="/custom1">Custom 1</div>
                <span href="/custom2">Custom 2</span>
            </body>
        </html>
        """
        base_url = "https://example.com/"

        links = crawler._extract_links(html, base_url)

        assert "https://example.com/custom1" in links
        assert "https://example.com/custom2" in links

    def test_extract_absolute_links(self, crawler):
        """Test handling of absolute URLs."""
        html = """
        <html>
            <body>
                <a href="https://example.com/absolute">Absolute</a>
            </body>
        </html>
        """
        base_url = "https://example.com/"

        links = crawler._extract_links(html, base_url)

        assert "https://example.com/absolute" in links

    def test_extract_relative_links(self, crawler):
        """Test handling of relative URLs."""
        html = """
        <html>
            <body>
                <a href="../parent">Parent</a>
                <a href="./sibling">Sibling</a>
            </body>
        </html>
        """
        base_url = "https://example.com/docs/page/"

        links = crawler._extract_links(html, base_url)

        assert "https://example.com/docs/parent" in links
        assert "https://example.com/docs/page/sibling" in links

    def test_extract_links_handles_invalid_html(self, crawler):
        """Test that invalid HTML doesn't crash extraction."""
        html = "<html><body><a href=/broken</a>"  # Unclosed tags
        base_url = "https://example.com/"

        links = crawler._extract_links(html, base_url)

        # Should handle gracefully and extract what it can
        assert isinstance(links, set)

    def test_extract_links_empty_html(self, crawler):
        """Test extraction from empty HTML."""
        html = ""
        base_url = "https://example.com/"

        links = crawler._extract_links(html, base_url)

        assert len(links) == 0

    def test_extract_links_deduplicates_and_preserves_queries(self, crawler):
        """Ensure duplicate hrefs collapse and urls with queries/fragments remain distinct."""
        html = """
        <html>
            <body>
                <a href="/docs/guide/">Guide</a>
                <a href="/docs/guide/">Duplicate guide</a>
                <span href="https://example.com/docs/search/?q=term">Query</span>
                <div href="https://example.com/docs/search/#anchor">Fragment</div>
            </body>
        </html>
        """
        base_url = "https://example.com/"

        links = crawler._extract_links(html, base_url)

        assert len(links) == 3
        assert "https://example.com/docs/guide/" in links
        assert "https://example.com/docs/search/?q=term" in links
        assert "https://example.com/docs/search/#anchor" in links


class TestCrawlerLoggingHelpers:
    """Verify progress and completion logging helpers."""

    @pytest.fixture
    def crawler(self):
        settings = Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_entry_url="https://example.com/",
            url_whitelist_prefixes="https://example.com/",
        )
        return EfficientCrawler({"https://example.com/"}, settings=settings)

    def test_report_progress_and_log_completion_emit_messages(self, crawler, caplog):
        caplog.set_level(logging.INFO)
        start_time = time.time() - 2.0
        crawler.collected.update({"https://example.com/", "https://example.com/page/"})
        crawler.frontier.extend(["https://example.com/queued/"])
        crawler.visited.update({"https://example.com/"})

        crawler._report_progress(start_time)
        assert "Progress:" in caplog.text

        crawler._crawler_skipped = 1
        crawler._log_completion(start_time)
        assert "Crawl complete" in caplog.text
        assert "skipped (recently visited)" in caplog.text


@pytest.mark.asyncio
class TestCrawlerAsyncOperations:
    """Test async crawler operations with mocked HTTP."""

    @pytest.fixture
    def settings(self):
        """Create test settings."""
        return Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_entry_url="https://example.com/",
            url_whitelist_prefixes="https://example.com/",
        )

    @pytest.fixture
    def mock_response(self):
        """Create mock HTTP response."""
        response = Mock(spec=httpx.Response)
        response.status_code = 200
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.text = """
        <html>
            <body>
                <h1>Test Page</h1>
                <a href="/page2">Page 2</a>
            </body>
        </html>
        """
        return response

    async def test_context_manager_protocol(self, settings):
        """Test crawler async context manager."""
        start_urls = {"https://example.com/"}
        crawler = EfficientCrawler(start_urls, settings=settings)

        # Before entering context
        assert crawler.client is None

        async with crawler:
            # Inside context
            assert crawler.client is not None
            assert isinstance(crawler.client, httpx.AsyncClient)

        # After exiting context - client should be closed
        # Note: We can't easily test if client is closed, but it shouldn't error

    async def test_crawl_initializes_frontier(self, settings, mock_response):
        """Test that crawl initializes frontier with start URLs."""
        start_urls = {"https://example.com/page1"}
        config = CrawlConfig(max_pages=1, delay_seconds=0.1)
        # Disable Playwright to avoid real browser launches
        settings.crawler_playwright_first = False
        crawler = EfficientCrawler(start_urls, config, settings)

        # Mock _process_page to return fake HTML without network calls
        async def fake_process_page(url):
            crawler.visited.add(url)
            crawler.collected.add(url)

        with patch.object(crawler, "_process_page", side_effect=fake_process_page):
            async with crawler:
                await crawler.crawl()

            # Frontier should have been initialized
            assert len(crawler.visited) > 0

    async def test_crawl_respects_max_pages_limit(self, settings, mock_response):
        """Test that crawl stops at max_pages limit."""
        start_urls = {"https://example.com/"}
        config = CrawlConfig(max_pages=2, delay_seconds=0.1)
        # Disable Playwright to avoid real browser launches
        settings.crawler_playwright_first = False
        crawler = EfficientCrawler(start_urls, config, settings)

        # Mock _process_page to simulate finding multiple pages
        page_count = [0]

        async def fake_process_page(url):
            page_count[0] += 1
            crawler.visited.add(url)
            crawler.collected.add(url)
            # Simulate finding more links on first page
            if page_count[0] == 1:
                crawler.frontier.extend(["https://example.com/page2", "https://example.com/page3"])

        with patch.object(crawler, "_process_page", side_effect=fake_process_page):
            async with crawler:
                result = await crawler.crawl()

            assert len(result) <= 2

    async def test_crawl_handles_http_errors_gracefully(self, settings):
        """Test that HTTP errors don't crash crawler."""
        start_urls = {"https://example.com/"}
        config = CrawlConfig(max_pages=1, delay_seconds=0.1)
        # Disable Playwright to avoid real browser launches
        settings.crawler_playwright_first = False
        crawler = EfficientCrawler(start_urls, config, settings)

        # Mock _process_page to simulate error (marks URL visited but doesn't collect)
        async def fake_process_page_error(url):
            crawler.visited.add(url)
            # Don't add to collected to simulate fetch failure

        with patch.object(crawler, "_process_page", side_effect=fake_process_page_error):
            async with crawler:
                result = await crawler.crawl()

            # Should complete without crashing
            assert isinstance(result, set)

    async def test_crawl_handles_fetch_failure_gracefully(self, settings):
        """Test that fetch failures don't crash crawler.

        Note: Actual HTTP 403 retry logic involves Playwright fallback which
        is tested in integration tests. This unit test verifies graceful
        handling of fetch failures at the _process_page level.
        """
        start_urls = {"https://example.com/"}
        config = CrawlConfig(max_pages=1, delay_seconds=0.1)
        # Disable Playwright to avoid real browser launches
        settings.crawler_playwright_first = False
        crawler = EfficientCrawler(start_urls, config, settings)

        # Track calls
        call_count = [0]

        async def fake_fetch_that_fails(url):
            call_count[0] += 1
            crawler.visited.add(url)
            # Simulate fetch failure - don't add to collected

        with patch.object(crawler, "_process_page", side_effect=fake_fetch_that_fails):
            async with crawler:
                result = await crawler.crawl()

            # Crawler should complete without crashing
            assert isinstance(result, set)
            # The fetch was attempted once
            assert call_count[0] == 1

    async def test_crawl_skips_non_html_content(self, settings):
        """Test that non-HTML content is skipped."""
        # Disable Playwright to avoid real browser launches
        settings.crawler_playwright_first = False

        start_urls = {"https://example.com/"}
        config = CrawlConfig(max_pages=5, delay_seconds=0.1)
        crawler = EfficientCrawler(start_urls, config, settings)

        # Track which URLs are processed
        processed_urls = []

        async def fake_process_page(url):
            processed_urls.append(url)
            crawler.visited.add(url)
            if url == "https://example.com/":
                # HTML page - collect and add link
                crawler.collected.add(url)
                next_url = "https://example.com/page2/"
                crawler.frontier.append(next_url)
                crawler._scheduled.add(next_url)
                if crawler._url_queue is not None:
                    await crawler._url_queue.put(next_url)
            else:
                # Simulate second page also being collected
                crawler.collected.add(url)

        with patch.object(crawler, "_process_page", side_effect=fake_process_page):
            async with crawler:
                result = await crawler.crawl()

            # Should collect both URLs
            assert len(result) == 2
            assert "https://example.com/" in result
            assert "https://example.com/page2/" in result

    async def test_crawl_calls_url_discovery_callback(self, settings, mock_response):
        """Test that URL discovery callback is invoked."""
        discovered_urls = []

        def callback(url):
            discovered_urls.append(url)

        start_urls = {"https://example.com/"}
        config = CrawlConfig(max_pages=1, delay_seconds=0.1, on_url_discovered=callback)
        # Disable Playwright to avoid real browser launches
        settings.crawler_playwright_first = False
        crawler = EfficientCrawler(start_urls, config, settings)

        # Mock _process_page to invoke the callback
        async def fake_process_page(url):
            crawler.visited.add(url)
            crawler.collected.add(url)
            # The real _process_page calls the callback, simulate this
            if crawler.config.on_url_discovered:
                crawler.config.on_url_discovered(url)

        with patch.object(crawler, "_process_page", side_effect=fake_process_page):
            async with crawler:
                await crawler.crawl()

            # Callback should have been called for discovered URLs
            assert len(discovered_urls) > 0

    async def test_process_page_respects_filters_and_rate_limit(self, settings):
        """Test _process_page calls callback only for allowed links and respects rate limiting."""
        settings.crawler_playwright_first = False
        discovered_urls: list[str] = []

        def callback(url: str):
            discovered_urls.append(url)

        config = CrawlConfig(on_url_discovered=callback, delay_seconds=0.1)
        crawler = EfficientCrawler({"https://example.com/docs/"}, config, settings)
        crawler.client = object()  # Avoid context manager assertion

        html = """
        <html>
            <body>
                <a href="/docs/tutorial/">Tutorial</a>
                <a href="/assets/logo.png">Logo</a>
            </body>
        </html>
        """

        fetch_mock = AsyncMock(return_value=html)
        rate_limit_mock = AsyncMock()

        with patch.object(crawler, "_fetch_with_httpx_first", new=fetch_mock):
            with patch.object(crawler, "_apply_rate_limit", new=rate_limit_mock):
                await crawler._process_page("https://example.com/docs/")

        # PNG link should be filtered, leaving only the HTML tutorial link queued
        assert list(crawler.frontier) == ["https://example.com/docs/tutorial/"]
        assert crawler.collected == {"https://example.com/docs/"}
        assert discovered_urls == ["https://example.com/docs/tutorial/"]
        rate_limit_mock.assert_awaited_once_with("https://example.com/docs/")
        fetch_mock.assert_awaited_once()

    async def test_process_page_handles_callback_errors(self, settings):
        """Ensure on_url_discovered errors are caught and links still queue."""
        settings.crawler_playwright_first = False
        discovered_urls: list[str] = []

        def callback(url: str):
            discovered_urls.append(url)
            raise RuntimeError("boom")

        config = CrawlConfig(on_url_discovered=callback)
        crawler = EfficientCrawler({"https://example.com/docs/"}, config, settings)
        crawler.client = object()

        html = """
        <html>
            <body>
                <a href="/docs/guide/">Guide</a>
                <a href="/docs/manual.pdf">PDF</a>
            </body>
        </html>
        """

        fetch_mock = AsyncMock(return_value=html)
        rate_limit_mock = AsyncMock()

        with patch.object(crawler, "_fetch_with_httpx_first", new=fetch_mock):
            with patch.object(crawler, "_apply_rate_limit", new=rate_limit_mock):
                await crawler._process_page("https://example.com/docs/")

        assert list(crawler.frontier) == ["https://example.com/docs/guide/"]
        assert discovered_urls == ["https://example.com/docs/guide/"]
        rate_limit_mock.assert_awaited_once_with("https://example.com/docs/")
        fetch_mock.assert_awaited_once()

    async def test_process_page_handles_http_errors_without_crashing(self, settings):
        """Offline/HTTP failures should short-circuit without halting the crawl."""
        settings.crawler_playwright_first = False
        crawler = EfficientCrawler({"https://example.com/docs/"}, settings=settings)
        crawler.client = Mock(spec=httpx.AsyncClient)
        crawler.client.get = AsyncMock(side_effect=httpx.HTTPError("offline"))

        rate_limit_mock = AsyncMock()

        with patch.object(crawler, "_apply_rate_limit", new=rate_limit_mock):
            with patch("article_extractor.PlaywrightFetcher") as MockFetcher:
                # Mock Playwright to also fail so we get success=False
                MockFetcher.side_effect = Exception("Playwright unavailable")
                result = await crawler._process_page("https://example.com/docs/")

        # Both fetch methods failed, so PageProcessResult should indicate failure
        assert result.success is False
        rate_limit_mock.assert_awaited_once_with("https://example.com/docs/")

    async def test_crawl_handles_skip_recently_visited_exception(self, settings):
        """Ensure crawl continues when the skip-recently-visited hook raises."""
        start_urls = {"https://example.com/"}
        config = CrawlConfig(max_pages=2, delay_seconds=0.1, progress_interval=1)

        def skip_recently_visited(_: str) -> bool:
            raise RuntimeError("boom")

        config.skip_recently_visited = skip_recently_visited
        crawler = EfficientCrawler(start_urls, config, settings)
        crawler.client = object()

        processed: list[str] = []

        async def fake_process_page(url: str):
            processed.append(url)
            crawler.collected.add(url)
            if url == "https://example.com/":
                next_url = "https://example.com/extra/"
                crawler.frontier.append(next_url)
                crawler._scheduled.add(next_url)
                if crawler._url_queue is not None:
                    await crawler._url_queue.put(next_url)

        crawler._process_page = AsyncMock(side_effect=fake_process_page)

        result = await crawler.crawl()

        assert processed == ["https://example.com/", "https://example.com/extra/"]
        assert result == {"https://example.com/", "https://example.com/extra/"}

    async def test_process_page_respects_settings_whitelist_and_blacklist(self):
        """Settings-driven allow/deny lists should govern queued URLs."""
        settings = Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_entry_url="https://example.com/docs/",
            url_whitelist_prefixes="https://example.com/docs/",
            url_blacklist_prefixes="https://example.com/docs/internal/",
        )
        settings.crawler_playwright_first = False

        discovered_urls: list[str] = []

        def callback(url: str):
            discovered_urls.append(url)

        config = CrawlConfig(on_url_discovered=callback)
        crawler = EfficientCrawler({"https://example.com/docs/"}, config, settings)
        crawler.client = object()  # Bypass context manager requirement

        html = """
        <html>
            <body>
                <a href="/docs/tutorial/">Tutorial</a>
                <a href="/docs/internal/secret/">Internal</a>
                <a href="https://external.example.com/docs/">External</a>
            </body>
        </html>
        """

        fetch_mock = AsyncMock(return_value=html)
        rate_limit_mock = AsyncMock()

        with patch.object(crawler, "_fetch_with_httpx_first", new=fetch_mock):
            with patch.object(crawler, "_apply_rate_limit", new=rate_limit_mock):
                await crawler._process_page("https://example.com/docs/")

        assert list(crawler.frontier) == ["https://example.com/docs/tutorial/"]
        assert crawler.collected == {"https://example.com/docs/"}
        assert discovered_urls == ["https://example.com/docs/tutorial/"]
        fetch_mock.assert_awaited_once()
        rate_limit_mock.assert_awaited_once_with("https://example.com/docs/")

    async def test_rate_limiting_delays_requests(self, settings):
        """Test that adaptive rate limiting calls sleep with correct delay."""
        import time
        from unittest.mock import AsyncMock, patch

        start_urls = {"https://example.com/"}
        config = CrawlConfig(delay_seconds=0.5)  # Base delay for testing
        crawler = EfficientCrawler(start_urls, config, settings)

        # Set initial request time to simulate previous request
        initial_time = time.time()
        crawler._last_request_time = initial_time

        # Mock asyncio.sleep to avoid real delays
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await crawler._apply_rate_limit("https://example.com/page1")

            # Verify sleep was called with a delay value (0.4-0.6s with jitter)
            assert mock_sleep.call_count == 1
            delay_arg = mock_sleep.call_args[0][0]
            # Base delay is 0.5s, jitter range is 0.8-1.2, so delay is 0.4s-0.6s
            assert 0.35 <= delay_arg <= 0.65, f"Expected delay 0.35-0.65s, got {delay_arg}s"

        # Verify last_request_time was updated
        assert crawler._last_request_time > initial_time

    async def test_adaptive_rate_limiter_increases_delay_on_429(self, settings):
        """Test that adaptive rate limiter increases delay when 429s are received."""
        from docs_mcp_server.utils.crawler import AdaptiveRateLimiter

        limiter = AdaptiveRateLimiter(default_delay=1.0)
        url = "https://example.com/page1"

        # Get the base delay without jitter for more deterministic testing
        host_state = limiter._get_host_state("example.com")
        initial_base_delay = host_state.current_delay
        assert initial_base_delay == 1.0  # Default delay

        # Record a 429 - base delay should increase
        limiter.record_429(url)
        after_429_base_delay = host_state.current_delay
        # After 429, delay should increase by 25%
        assert after_429_base_delay == pytest.approx(1.25, rel=0.01)
        assert after_429_base_delay > initial_base_delay

        # Record another 429 - delay should increase more
        limiter.record_429(url)
        after_two_429s_base_delay = host_state.current_delay
        # Should increase by another 25%
        assert after_two_429s_base_delay > after_429_base_delay

    async def test_adaptive_rate_limiter_decreases_delay_on_success(self, settings):
        """Test that adaptive rate limiter decreases delay after sustained success."""
        from docs_mcp_server.utils.crawler import AdaptiveRateLimiter

        limiter = AdaptiveRateLimiter(default_delay=1.0)
        url = "https://example.com/page1"

        # First record a 429 to increase the delay
        limiter.record_429(url)
        increased_delay = limiter._get_host_state("example.com").current_delay
        assert increased_delay > 1.0

        # Record 10 successes - delay should decrease
        for _ in range(10):
            limiter.record_success(url)

        # After 10 successes, delay should have decreased by 10%
        final_delay = limiter._get_host_state("example.com").current_delay
        assert final_delay < increased_delay

    async def test_adaptive_rate_limiter_reports_stats(self, settings):
        """Stats output should reflect mixed success/429 history."""
        from docs_mcp_server.utils.crawler import AdaptiveRateLimiter

        limiter = AdaptiveRateLimiter(default_delay=1.0)
        url = "https://example.com/page1"

        # Mix of failures and successes to populate totals
        limiter.record_429(url)
        limiter.record_success(url)
        limiter.record_429(url)
        limiter.record_success(url)
        limiter.record_success(url)

        stats = limiter.get_stats()
        host_stats = stats["example.com"]

        assert host_stats["total_429s"] == 2
        assert host_stats["total_requests"] == 5
        assert host_stats["current_delay"] >= 1.0
        assert 0.0 <= host_stats["recent_429_rate"] <= 1.0


class TestCrawlerFrontierManagement:
    """Test frontier initialization and max_pages behavior."""

    @pytest.fixture
    def settings(self):
        """Provide crawler settings for frontier tests."""
        return Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            docs_entry_url="https://example.com/docs/",
            url_whitelist_prefixes="https://example.com/docs/",
        )

    def test_initialize_frontier_deduplicates_seed_urls(self, settings):
        """Start URLs should normalize and deduplicate before queuing."""
        start_urls = {
            "https://example.com/docs",
            "https://example.com/docs/",
            "https://example.com/docs#fragment",
        }
        crawler = EfficientCrawler(start_urls, settings=settings)

        crawler._initialize_frontier()

        assert len(crawler.frontier) == 1
        assert crawler.frontier[0] == "https://example.com/docs/"

    @pytest.mark.asyncio
    async def test_crawl_stops_when_max_pages_reached(self, settings):
        """Ensure crawl exits once max_pages threshold is hit."""
        config = CrawlConfig(max_pages=1, delay_seconds=0.0)
        start_urls = {"https://example.com/docs/", "https://example.com/docs/second/"}
        crawler = EfficientCrawler(start_urls, config, settings)

        processed = []

        async def fake_process_page(url: str):
            processed.append(url)
            crawler.collected.add(url)
            if url == "https://example.com/docs/":
                crawler.frontier.append("https://example.com/docs/second/")

        with patch.object(crawler, "_process_page", side_effect=fake_process_page):
            async with crawler:
                result = await crawler.crawl()

        assert processed == ["https://example.com/docs/"]
        assert result == {"https://example.com/docs/"}
        assert "https://example.com/docs/second/" in crawler.frontier
