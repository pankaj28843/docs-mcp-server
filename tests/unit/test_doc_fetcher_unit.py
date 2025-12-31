"""Unit tests for AsyncDocFetcher using article-extractor.

Tests the document fetching logic, title extraction, and markdown cleaning.
Uses article-extractor for content extraction (pure Python, no external services).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _import_doc_fetcher():
    """Import doc_fetcher module avoiding circular imports."""
    try:
        from docs_mcp_server.utils import doc_fetcher

        return doc_fetcher
    except ImportError:
        from docs_mcp_server import config  # noqa: F401
        from docs_mcp_server.utils import doc_fetcher

        return doc_fetcher


def _create_mock_settings():
    """Create mock settings for testing."""
    settings = MagicMock()
    settings.http_timeout = 30
    settings.max_concurrent_requests = 10
    settings.request_delay_ms = 100
    settings.snippet_length = 200
    settings.get_random_user_agent.return_value = "Mozilla/5.0 Test"
    settings.markdown_url_suffix = ""
    return settings


@pytest.mark.unit
class TestAsyncDocFetcherInit:
    """Tests for AsyncDocFetcher initialization."""

    def test_init_sets_attributes_from_settings(self):
        """Test that init properly sets attributes from settings."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()

        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        assert fetcher.http_timeout == 30
        assert fetcher.max_concurrent_requests == 10
        assert fetcher.snippet_length == 200

    def test_init_creates_extraction_options(self):
        """Test that extraction options are created with defaults."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()

        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        assert fetcher._extraction_options is not None
        assert fetcher._extraction_options.min_word_count == 150
        assert fetcher._extraction_options.safe_markdown is True


@pytest.mark.unit
class TestExtractTitle:
    """Tests for _extract_title method."""

    def test_returns_title_when_present(self):
        """Test that title is returned when present in result."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        result = SimpleNamespace(title="Test Title", excerpt="Some excerpt")
        title = fetcher._extract_title(result, "https://example.com/doc")

        assert title == "Test Title"

    def test_returns_stripped_title(self):
        """Test that title is stripped of whitespace."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        result = SimpleNamespace(title="  Test Title  ", excerpt="")
        title = fetcher._extract_title(result, "https://example.com/doc")

        assert title == "Test Title"

    def test_uses_excerpt_first_sentence_when_no_title(self):
        """Test fallback to excerpt when no title."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        result = SimpleNamespace(title="", excerpt="This is a good excerpt. More text follows.")
        title = fetcher._extract_title(result, "https://example.com/doc")

        assert title == "This is a good excerpt"

    def test_url_fallback_when_no_title_or_excerpt(self):
        """Test fallback to URL when no title or excerpt."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        result = SimpleNamespace(title="", excerpt="")
        title = fetcher._extract_title(result, "https://example.com/my-page")

        assert title == "My Page"


@pytest.mark.unit
class TestGenerateExcerpt:
    """Tests for _generate_excerpt method."""

    def test_uses_excerpt_when_long_enough(self):
        """Test that long excerpts are used directly."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.snippet_length = 200
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        long_excerpt = "x" * 100  # More than 50 chars
        result = SimpleNamespace(excerpt=long_excerpt)
        excerpt = fetcher._generate_excerpt(result, "Some markdown content")

        assert excerpt == long_excerpt

    def test_truncates_long_excerpt(self):
        """Test that very long excerpts are truncated."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.snippet_length = 50
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        long_excerpt = "x" * 100  # More than snippet_length
        result = SimpleNamespace(excerpt=long_excerpt)
        excerpt = fetcher._generate_excerpt(result, "Some markdown content")

        assert len(excerpt) == 53  # 50 + "..."
        assert excerpt.endswith("...")

    def test_generates_from_markdown_when_short_excerpt(self):
        """Test that markdown is used when excerpt is short."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.snippet_length = 200
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        result = SimpleNamespace(excerpt="too short")  # Less than 50 chars
        markdown = "Line one content\nLine two content\nLine three content"
        excerpt = fetcher._generate_excerpt(result, markdown)

        assert "Line one content" in excerpt


@pytest.mark.unit
class TestCleanMarkdown:
    """Tests for _clean_markdown method."""

    def test_removes_excessive_blank_lines(self):
        """Test that multiple blank lines are collapsed."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        markdown = "Line 1\n\n\n\n\nLine 2"
        cleaned = fetcher._clean_markdown(markdown)

        assert "\n\n\n" not in cleaned
        assert "Line 1" in cleaned
        assert "Line 2" in cleaned

    def test_removes_excessive_whitespace(self):
        """Test that multiple spaces are collapsed."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        markdown = "Text    with    spaces"
        cleaned = fetcher._clean_markdown(markdown)

        assert "    " not in cleaned


@pytest.mark.unit
class TestDirectMarkdownFetching:
    """Tests for direct markdown URL fetching."""

    def test_build_markdown_candidate_url_with_suffix(self):
        """Test building markdown URL with suffix."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.markdown_url_suffix = ".md"
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        url = fetcher._build_markdown_candidate_url("https://example.com/docs/page")
        assert url == "https://example.com/docs/page.md"

    def test_build_markdown_candidate_url_replaces_html(self):
        """Test that .html extension is replaced."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.markdown_url_suffix = ".md"
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        url = fetcher._build_markdown_candidate_url("https://example.com/docs/page.html")
        assert url == "https://example.com/docs/page.md"

    def test_build_markdown_candidate_url_returns_none_without_suffix(self):
        """Test that None is returned when no suffix configured."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.markdown_url_suffix = ""
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        url = fetcher._build_markdown_candidate_url("https://example.com/docs/page")
        assert url is None

    def test_derive_markdown_title_from_heading(self):
        """Test title extraction from markdown heading."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        markdown = "# My Page Title\n\nSome content here."
        title = fetcher._derive_markdown_title(markdown, "https://example.com/fallback")

        assert title == "My Page Title"

    def test_derive_markdown_title_url_fallback(self):
        """Test URL fallback for title when no heading."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        markdown = "No heading here, just content."
        title = fetcher._derive_markdown_title(markdown, "https://example.com/my-doc")

        assert title == "My Doc"


@pytest.mark.unit
class TestAsyncContextManagerLifecycle:
    """Tests for async context manager lifecycle."""

    @pytest.mark.asyncio
    async def test_context_manager_initializes_playwright(self, monkeypatch):
        """Test that context manager initializes PlaywrightFetcher."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()

        # Mock PlaywrightFetcher
        mock_playwright = AsyncMock()
        mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
        mock_playwright.__aexit__ = AsyncMock()
        mock_playwright._context = MagicMock()  # Simulate initialized context

        monkeypatch.setattr(doc_fetcher, "PlaywrightFetcher", lambda: mock_playwright)

        fetcher = doc_fetcher.AsyncDocFetcher(settings)
        async with fetcher:
            assert fetcher.playwright_fetcher is not None

    @pytest.mark.asyncio
    async def test_context_manager_closes_resources(self, monkeypatch):
        """Test that context manager closes resources on exit."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()

        # Mock PlaywrightFetcher
        mock_playwright = AsyncMock()
        mock_playwright.__aenter__ = AsyncMock(return_value=mock_playwright)
        mock_playwright.__aexit__ = AsyncMock()
        mock_playwright._context = MagicMock()

        monkeypatch.setattr(doc_fetcher, "PlaywrightFetcher", lambda: mock_playwright)

        fetcher = doc_fetcher.AsyncDocFetcher(settings)
        async with fetcher:
            pass

        mock_playwright.__aexit__.assert_called_once()


@pytest.mark.unit
class TestFetchAndExtract:
    """Tests for _fetch_and_extract method."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_playwright_fetcher(self, monkeypatch):
        """Test that None is returned when PlaywrightFetcher is not initialized."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)
        fetcher.playwright_fetcher = None

        result = await fetcher._fetch_and_extract("https://example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_fetch_fails(self, monkeypatch):
        """Test that None is returned when fetch returns non-200."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        # Mock playwright fetcher
        mock_playwright = AsyncMock()
        mock_playwright._context = MagicMock()
        mock_playwright.fetch = AsyncMock(return_value=("", 404))
        fetcher.playwright_fetcher = mock_playwright

        result = await fetcher._fetch_and_extract("https://example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_docpage_on_success(self, monkeypatch):
        """Test that DocPage is returned on successful extraction."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        # Mock playwright fetcher
        mock_playwright = AsyncMock()
        mock_playwright._context = MagicMock()
        mock_playwright.fetch = AsyncMock(
            return_value=(
                "<html><body><article><h1>Test</h1><p>Content here.</p></article></body></html>",
                200,
            )
        )
        fetcher.playwright_fetcher = mock_playwright

        # Mock extract_article to return a successful result
        mock_result = SimpleNamespace(
            success=True,
            title="Test",
            content="<p>Content here.</p>",
            markdown="# Test\n\nContent here.",
            excerpt="Content here.",
            word_count=2,
            error=None,
        )
        monkeypatch.setattr(doc_fetcher, "extract_article", lambda *args, **kwargs: mock_result)

        result = await fetcher._fetch_and_extract("https://example.com/test")

        assert result is not None
        assert result.title == "Test"
        assert result.extraction_method == "article_extractor"


@pytest.mark.unit
class TestConvertToDocPage:
    """Tests for _convert_to_doc_page method."""

    def test_returns_none_when_no_content(self):
        """Test that None is returned when result has no content."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        result = SimpleNamespace(
            success=True,
            title="",
            content="",
            markdown="",
            excerpt="",
            word_count=0,
            error=None,
        )

        doc_page = fetcher._convert_to_doc_page("https://example.com", result)
        assert doc_page is None

    def test_returns_docpage_with_content(self):
        """Test that DocPage is returned with valid content."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        result = SimpleNamespace(
            success=True,
            title="Test Title",
            content="<p>Content</p>",
            markdown="# Test Title\n\nContent",
            excerpt="Content",
            word_count=2,
            error=None,
        )

        doc_page = fetcher._convert_to_doc_page("https://example.com", result)

        assert doc_page is not None
        assert doc_page.title == "Test Title"
        assert doc_page.url == "https://example.com"
        assert doc_page.extraction_method == "article_extractor"
        assert "Content" in doc_page.content
