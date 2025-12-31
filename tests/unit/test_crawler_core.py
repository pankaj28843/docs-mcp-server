"""Unit tests for Crawler core logic (crawl, process_page)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docs_mcp_server.utils.crawler import CrawlConfig, EfficientCrawler


@pytest.fixture
def crawl_config():
    return CrawlConfig(
        max_pages=10,
        delay_seconds=0.0,  # No delay for tests
    )


@pytest.fixture
def crawler(crawl_config):
    return EfficientCrawler(start_urls={"http://example.com"}, crawl_config=crawl_config)


@pytest.mark.unit
class TestCrawlerCore:
    """Test Crawler core logic."""

    async def test_crawl_single_page(self, crawler):
        """Test crawling a single page."""
        # Mock client
        mock_client = AsyncMock()

        # Mock _create_client to return our mock
        with patch.object(crawler, "_create_client", return_value=mock_client):
            # Mock process_page to avoid actual processing logic for now
            with patch.object(crawler, "_process_page", new_callable=AsyncMock) as mock_process:
                # Side effect to simulate successful processing
                def side_effect(url):
                    crawler.collected.add(url)
                    crawler.output_collected.add(url)

                mock_process.side_effect = side_effect

                async with crawler:
                    results = await crawler.crawl()

                assert len(results) == 1
                # Expect normalized URL (trailing slash)
                assert "http://example.com/" in results
                mock_process.assert_called_once()

    async def test_crawl_max_pages(self, crawler):
        """Test max pages limit."""
        crawler.config.max_pages = 1

        # Mock client
        mock_client = AsyncMock()

        with patch.object(crawler, "_create_client", return_value=mock_client):
            with patch.object(crawler, "_process_page", new_callable=AsyncMock) as mock_process:
                # First call returns content and adds to frontier
                def side_effect(url):
                    crawler.collected.add(url)
                    crawler.output_collected.add(url)
                    crawler.frontier.append("http://example.com/page2")

                mock_process.side_effect = side_effect

                async with crawler:
                    results = await crawler.crawl()

                assert len(results) == 1
                # Frontier might have more, but we stopped processing

    async def test_crawl_visited_tracking(self, crawler):
        """Test that visited URLs are not recrawled."""
        # Add normalized URL to visited
        crawler.visited.add("http://example.com/")

        with patch.object(crawler, "_create_client", return_value=AsyncMock()):
            async with crawler:
                results = await crawler.crawl()

            assert len(results) == 0

    async def test_process_page_success(self, crawler):
        """Test successful page processing."""
        crawler.client = AsyncMock()

        # Mock fetch strategy
        with patch.object(crawler, "_fetch_with_httpx_first", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = "<html><a href='/link'>Link</a></html>"

            await crawler._process_page("http://example.com")

            assert "http://example.com" in crawler.collected
            assert any(url.startswith("http://example.com") for url in crawler.output_collected)
            # Check if link was added to frontier
            assert len(crawler.frontier) > 0
            # Expect normalized URL (trailing slash added by default)
            assert "http://example.com/link/" in crawler.frontier

    async def test_process_page_failure(self, crawler):
        """Test page processing failure."""
        crawler.client = AsyncMock()

        with patch.object(crawler, "_fetch_with_httpx_first", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = None  # Fetch failed

            await crawler._process_page("http://example.com")

            assert "http://example.com" not in crawler.collected
            assert len(crawler.frontier) == 0

    async def test_process_page_emits_markdown_urls_when_configured(self, crawler):
        """Ensure discovery callback receives Markdown mirrors when suffix configured."""

        crawler.config.markdown_url_suffix = ".md"
        crawler._markdown_url_suffix = ".md"
        crawler._normalized_seed_urls = {"http://example.com/docs"}
        crawler.client = AsyncMock()

        with patch.object(crawler, "_fetch_with_httpx_first", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = "<html><a href='/docs/messaging'>SMS</a></html>"
            discovered: list[str] = []
            crawler.config.on_url_discovered = discovered.append

            await crawler._process_page("http://example.com/docs")

        assert any(url.endswith("messaging.md") for url in discovered)

    def test_extract_links(self, crawler):
        """Test link extraction."""
        html = """
        <html>
            <body>
                <a href="/local">Local</a>
                <a href="http://example.com/absolute">Absolute</a>
                <a href="http://other.com">External</a>
                <a href="#fragment">Fragment</a>
                <a href="mailto:user@example.com">Mailto</a>
            </body>
        </html>
        """

        # Correct argument order: html_content, url
        links = crawler._extract_links(html, "http://example.com")

        assert "http://example.com/local" in links
        assert "http://example.com/absolute" in links
        assert "http://other.com" in links  # _extract_links does NOT filter
        assert "http://example.com#fragment" in links  # urljoin result
        assert "mailto:user@example.com" in links

    def test_should_crawl_url_host_check(self, crawler):
        """Test host checking in _should_crawl_url."""
        # Same host
        assert crawler._should_crawl_url("http://example.com/page") is True
        assert crawler._should_crawl_url("http://other.com/page") is False

    def test_should_process_url_settings(self, crawler):
        """Test URL filtering via settings in _should_process_url."""
        crawler.settings = MagicMock()

        # Mock settings.should_process_url
        crawler.settings.should_process_url.side_effect = lambda url: "docs" in url

        assert crawler._should_process_url("http://example.com/docs/page") is True
        assert crawler._should_process_url("http://example.com/other") is False
