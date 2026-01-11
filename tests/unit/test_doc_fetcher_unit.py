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
        from docs_mcp_server.utils import doc_fetcher  # noqa: PLC0415

        return doc_fetcher
    except ImportError:
        from docs_mcp_server import config  # noqa: F401, PLC0415
        from docs_mcp_server.utils import doc_fetcher  # noqa: PLC0415

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
    settings.fallback_extractor_enabled = False
    settings.fallback_extractor_endpoint = ""
    settings.fallback_extractor_timeout_seconds = 20
    settings.fallback_extractor_batch_size = 1
    settings.fallback_extractor_max_retries = 0
    settings.fallback_extractor_api_key = None
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
        fetcher.session = object()

        result = SimpleNamespace(title="Test Title", excerpt="Some excerpt")
        title = fetcher._extract_title(result, "https://example.com/doc")

        assert title == "Test Title"

    def test_returns_stripped_title(self):
        """Test that title is stripped of whitespace."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)
        fetcher.session = object()

        result = SimpleNamespace(title="  Test Title  ", excerpt="")
        title = fetcher._extract_title(result, "https://example.com/doc")

        assert title == "Test Title"

    def test_uses_excerpt_first_sentence_when_no_title(self):
        """Test fallback to excerpt when no title."""
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)
        fetcher.session = object()

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

    def test_build_markdown_candidate_url_skips_non_html_extensions(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.markdown_url_suffix = ".md"
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        url = fetcher._build_markdown_candidate_url("https://example.com/docs/page.pdf")
        assert url is None

    def test_prepare_direct_markdown_normalizes_bom_and_whitespace(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        raw = "\ufeff# Title\r\n\r\nParagraph\r\n\r\n\r\n```\r\ncode\r\n```\r\n"
        prepared = fetcher._prepare_direct_markdown(raw)

        assert prepared.startswith("# Title")
        assert prepared.endswith("\n")
        assert "\r\n" not in prepared

    def test_prepare_direct_markdown_returns_empty_for_blank(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        assert fetcher._prepare_direct_markdown("   ") == ""

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

    def test_should_skip_fallback_detects_static_assets(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        assert fetcher._should_skip_fallback("https://example.com/_static/app.js") is True
        assert fetcher._should_skip_fallback("https://example.com/docs/guide/") is False

    def test_get_fallback_metrics_returns_counts(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        assert fetcher.get_fallback_metrics() == {
            "fallback_attempts": 0,
            "fallback_successes": 0,
            "fallback_failures": 0,
        }

    @pytest.mark.asyncio
    async def test_fetch_direct_markdown_returns_doc_page(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.markdown_url_suffix = ".md"
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        response = SimpleNamespace(status=200, text=AsyncMock(return_value="# Title\n\nBody\n"))
        fetcher.session = SimpleNamespace(get=AsyncMock(return_value=response))

        page = await fetcher._fetch_direct_markdown("https://example.com/docs/page")

        assert page is not None
        assert page.extraction_method == "direct_markdown"
        assert page.title == "Title"

    @pytest.mark.asyncio
    async def test_fetch_direct_markdown_returns_none_on_non_200(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.markdown_url_suffix = ".md"
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        response = SimpleNamespace(status=404, text=AsyncMock(return_value=""))
        fetcher.session = SimpleNamespace(get=AsyncMock(return_value=response))

        page = await fetcher._fetch_direct_markdown("https://example.com/docs/missing")

        assert page is None


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

    @pytest.mark.asyncio
    async def test_context_manager_handles_playwright_failure(self, monkeypatch):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()

        class BrokenFetcher:
            async def __aenter__(self):
                raise RuntimeError("boom")

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        monkeypatch.setattr(doc_fetcher, "PlaywrightFetcher", lambda: BrokenFetcher())

        fetcher = doc_fetcher.AsyncDocFetcher(settings)
        with pytest.raises(RuntimeError):
            async with fetcher:
                pass
        assert fetcher.playwright_fetcher is None

    @pytest.mark.asyncio
    async def test_context_manager_skips_when_fetcher_preloaded(self, monkeypatch):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)
        fetcher.playwright_fetcher = AsyncMock()

        monkeypatch.setattr(doc_fetcher, "PlaywrightFetcher", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        async with fetcher:
            assert fetcher.playwright_fetcher is not None

    @pytest.mark.asyncio
    async def test_aexit_noop_without_playwright_fetcher(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        await fetcher.__aexit__(None, None, None)

        assert fetcher.playwright_fetcher is None


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

    @pytest.mark.asyncio
    async def test_returns_none_when_context_missing(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        mock_playwright = AsyncMock()
        mock_playwright._context = None
        fetcher.playwright_fetcher = mock_playwright

        result = await fetcher._fetch_and_extract("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_extraction_fails(self, monkeypatch):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        mock_playwright = AsyncMock()
        mock_playwright._context = MagicMock()
        mock_playwright.fetch = AsyncMock(return_value=("<html></html>", 200))
        fetcher.playwright_fetcher = mock_playwright

        mock_result = SimpleNamespace(success=False, error="bad", title="", content="", markdown="")
        monkeypatch.setattr(doc_fetcher, "extract_article", lambda *args, **kwargs: mock_result)

        result = await fetcher._fetch_and_extract("https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_fetch_raises(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        mock_playwright = AsyncMock()
        mock_playwright._context = MagicMock()
        mock_playwright.fetch = AsyncMock(side_effect=RuntimeError("boom"))
        fetcher.playwright_fetcher = mock_playwright

        result = await fetcher._fetch_and_extract("https://example.com")

        assert result is None


@pytest.mark.unit
class TestFetchPage:
    @pytest.mark.asyncio
    async def test_fetch_page_uses_direct_markdown(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        page = SimpleNamespace(extraction_method="direct_markdown")
        fetcher._fetch_direct_markdown = AsyncMock(return_value=page)
        fetcher._fetch_and_extract = AsyncMock()
        fetcher._fetch_with_fallback = AsyncMock()

        result = await fetcher.fetch_page("https://example.com")

        assert result is page
        fetcher._fetch_and_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_page_raises_doc_fetch_error(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        fetcher._fetch_direct_markdown = AsyncMock(return_value=None)
        fetcher._fetch_and_extract = AsyncMock(return_value=None)
        fetcher._fetch_with_fallback = AsyncMock(return_value=(None, "fallback_disabled"))

        with pytest.raises(doc_fetcher.DocFetchError) as exc:
            await fetcher.fetch_page("https://example.com")

        assert exc.value.reason == "fallback_disabled"

    @pytest.mark.asyncio
    async def test_fetch_page_logs_playwright_failure(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        fetcher.playwright_fetcher = AsyncMock()
        fetcher._fetch_direct_markdown = AsyncMock(return_value=None)
        fetcher._fetch_and_extract = AsyncMock(return_value=None)
        fetcher._fetch_with_fallback = AsyncMock(return_value=(SimpleNamespace(ok=True), None))

        result = await fetcher.fetch_page("https://example.com")

        assert result.ok is True


@pytest.mark.unit
class TestConversionHelpers:
    def test_convert_to_doc_page_returns_none_when_empty(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        result = SimpleNamespace(content="", markdown="", title="Title", excerpt="")

        assert fetcher._convert_to_doc_page("https://example.com", result) is None

    def test_extract_title_uses_excerpt_sentence(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        result = SimpleNamespace(title="", excerpt="This is a long excerpt sentence. More.")
        title = fetcher._extract_title(result, "https://example.com/doc")

        assert title == "This is a long excerpt sentence"

    def test_extract_title_falls_back_to_url_when_empty(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        result = SimpleNamespace(title="", excerpt="")
        title = fetcher._extract_title(result, "")

        assert title == ""

    def test_generate_excerpt_from_markdown_text_empty(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        assert fetcher._generate_excerpt_from_markdown_text("") == ""

    def test_build_markdown_candidate_url_returns_none_for_root(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.markdown_url_suffix = ".md"
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        assert fetcher._build_markdown_candidate_url("https://example.com/") is None

    def test_generate_excerpt_returns_markdown_when_no_content_lines(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        result = SimpleNamespace(excerpt="short")
        excerpt = fetcher._generate_excerpt(result, "# Heading\n\n")

        assert excerpt.strip() == "# Heading"

    def test_prepare_direct_markdown_handles_empty_string(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        assert fetcher._prepare_direct_markdown("") == ""

    def test_prepare_direct_markdown_appends_newline(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        prepared = fetcher._prepare_direct_markdown("# Title")

        assert prepared.endswith("\n")

    def test_build_markdown_candidate_url_handles_existing_suffix(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.markdown_url_suffix = ".md"
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        url = fetcher._build_markdown_candidate_url("https://example.com/docs/page.md")

        assert url == "https://example.com/docs/page.md"


@pytest.mark.unit
class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_apply_rate_limit_sleeps_when_needed(self, monkeypatch):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)
        fetcher._request_delay = 0.2
        fetcher._last_request_time = 1.0

        times = {"now": 1.05}

        def fake_time():
            return times["now"]

        async def fake_sleep(duration: float):
            times["now"] += duration

        monkeypatch.setattr(doc_fetcher.asyncio.get_event_loop(), "time", fake_time)
        monkeypatch.setattr(doc_fetcher.asyncio, "sleep", fake_sleep)

        await fetcher._apply_rate_limit()

        assert fetcher._last_request_time >= 1.2


@pytest.mark.unit
class TestFallbackPayloads:
    @pytest.mark.asyncio
    async def test_fetch_with_fallback_skips_assets(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.fallback_extractor_enabled = True
        settings.fallback_extractor_endpoint = "https://fallback"
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        page, reason = await fetcher._fetch_with_fallback("https://example.com/_static/app.js")

        assert page is None
        assert reason == "fallback_skipped_asset"

    @pytest.mark.asyncio
    async def test_fetch_with_fallback_disabled(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        page, reason = await fetcher._fetch_with_fallback("https://example.com/doc")

        assert page is None
        assert reason == "fallback_disabled"

    @pytest.mark.asyncio
    async def test_fetch_with_fallback_retries_and_reports_failure(self, monkeypatch):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.fallback_extractor_enabled = True
        settings.fallback_extractor_endpoint = "https://fallback"
        settings.fallback_extractor_max_retries = 1
        settings.fallback_extractor_api_key = "secret"
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        class FakeResponse:
            status = 200

            async def json(self):
                return {}

            async def text(self):
                return ""

        class FakeSession:
            async def post(self, *args, **kwargs):
                return FakeResponse()

        def fake_create_session():
            fetcher.session = FakeSession()

        async def fake_sleep(_seconds: float):
            return None

        monkeypatch.setattr(fetcher, "_create_session", fake_create_session)
        monkeypatch.setattr(doc_fetcher.asyncio, "sleep", fake_sleep)

        page, reason = await fetcher._fetch_with_fallback("https://example.com/doc")

        assert page is None
        assert "fallback returned empty payload" in reason

    def test_convert_fallback_payload_returns_none_when_empty(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        assert fetcher._convert_fallback_payload("https://example.com", {}) is None

    def test_convert_fallback_payload_uses_html_content(self):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        payload = {"html": "# Title\n\nBody"}
        result = fetcher._convert_fallback_payload("https://example.com/doc", payload)

        assert result is not None


@pytest.mark.unit
class TestTransient404Extraction:
    """Tests for transient 404/410 handling per article-extractor 0.4.1.

    article-extractor 0.4.1 introduces heuristics that allow extraction
    from 404/410 responses when the HTML looks substantial (SPA pattern).
    These tests verify docs-mcp-server correctly routes to that logic.

    See: .github/ai-agent-plans/2026-01-04T10-08-00Z-article-extractor-404-plan.md
    """

    # Synthetic SPA 404 HTML with substantial content that should pass extraction
    SPA_404_HTML = """<!DOCTYPE html>
<html>
<head><title>Feature Documentation - MyApp</title></head>
<body>
<article>
<h1>Feature Documentation</h1>
<p>This feature allows users to configure advanced settings for their application.
The configuration options include network timeouts, retry policies, and caching behavior.</p>
<h2>Configuration Options</h2>
<p>Use the settings panel to adjust the following parameters:</p>
<ul>
<li>Timeout: Maximum time to wait for a response</li>
<li>Retries: Number of retry attempts on failure</li>
<li>Cache TTL: How long to cache responses</li>
</ul>
<p>For more information, see the API reference documentation.</p>
</article>
</body>
</html>"""

    # Minimal 404 page that should NOT be extracted (too sparse)
    SPARSE_404_HTML = """<!DOCTYPE html>
<html>
<head><title>Not Found</title></head>
<body>
<h1>404 Not Found</h1>
<p>The requested page could not be found.</p>
</body>
</html>"""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Pending implementation: Step 1.1 of article-extractor 404 plan")
    async def test_extracts_content_from_spa_404_response(self):
        """SPA 404 with substantial HTML should be extracted successfully.

        When Playwright returns a 404 status but the HTML contains <article>
        with substantial content (>500 chars), article-extractor should
        attempt extraction and succeed. The result should include a warning
        indicating SPA/transient extraction.
        """
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        mock_playwright = AsyncMock()
        mock_playwright._context = MagicMock()
        mock_playwright.fetch = AsyncMock(return_value=(self.SPA_404_HTML, 404))
        fetcher.playwright_fetcher = mock_playwright

        result = await fetcher._fetch_and_extract("https://example.com/spa-feature")

        # Should succeed because HTML is substantial and extractable
        assert result is not None
        assert result.title == "Feature Documentation"
        assert "configuration" in result.content.lower()
        assert result.extraction_method == "article_extractor"

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Pending implementation: Step 1.3 of article-extractor 404 plan")
    async def test_spa_404_includes_warning_metadata(self):
        """SPA 404 extraction should propagate warning about transient status.

        article-extractor 0.4.1 appends warnings like:
        "Extracted after HTTP 404 (SPA/client-rendered)"

        This test verifies the warning flows through to the DocPage or logs.
        """
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        mock_playwright = AsyncMock()
        mock_playwright._context = MagicMock()
        mock_playwright.fetch = AsyncMock(return_value=(self.SPA_404_HTML, 404))
        fetcher.playwright_fetcher = mock_playwright

        result = await fetcher._fetch_and_extract("https://example.com/spa-feature")

        # Result should exist and readability_content should capture warning
        assert result is not None
        # The warning metadata should be accessible (exact field TBD in implementation)
        # For now we just verify the extraction succeeded
        assert result.extraction_method == "article_extractor"

    @pytest.mark.asyncio
    async def test_rejects_sparse_404_response(self):
        """Sparse 404 pages should be rejected (not cached).

        When a 404 response has minimal HTML (< 500 chars, no <article>),
        it's a genuine 404 error page and should return None.
        This is the EXISTING correct behavior that must be preserved.
        """
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        mock_playwright = AsyncMock()
        mock_playwright._context = MagicMock()
        mock_playwright.fetch = AsyncMock(return_value=(self.SPARSE_404_HTML, 404))
        fetcher.playwright_fetcher = mock_playwright

        result = await fetcher._fetch_and_extract("https://example.com/not-found")

        # Should return None because the HTML is sparse (genuine 404)
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Pending implementation: Step 1.1 of article-extractor 404 plan")
    async def test_extracts_content_from_410_response(self):
        """HTTP 410 (Gone) should receive same treatment as 404.

        Per article-extractor 0.4.1, both 404 and 410 are transient
        client errors that warrant extraction attempts on substantial HTML.
        """
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        fetcher = doc_fetcher.AsyncDocFetcher(settings)

        mock_playwright = AsyncMock()
        mock_playwright._context = MagicMock()
        mock_playwright.fetch = AsyncMock(return_value=(self.SPA_404_HTML, 410))
        fetcher.playwright_fetcher = mock_playwright

        result = await fetcher._fetch_and_extract("https://example.com/archived-page")

        assert result is not None
        assert result.title == "Feature Documentation"


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


@pytest.mark.unit
class TestFallbackExtractor:
    """Tests covering the remote fallback integration."""

    @pytest.mark.asyncio
    async def test_fallback_returns_doc_page_on_success(self, monkeypatch):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.fallback_extractor_enabled = True
        settings.fallback_extractor_endpoint = "http://fallback.local"
        settings.fallback_extractor_timeout_seconds = 5
        settings.fallback_extractor_max_retries = 0

        fetcher = doc_fetcher.AsyncDocFetcher(settings)
        fetcher.session = AsyncMock()

        response_payload = {
            "title": "Remote Title",
            "markdown": "# Remote Title\n\nRemote content",
            "content": "<h1>Remote Title</h1>",
            "excerpt": "Remote content excerpt",
        }

        dummy_response = SimpleNamespace(
            status=200,
            json=AsyncMock(return_value=response_payload),
            text=AsyncMock(return_value=""),
        )
        fetcher.session.post.return_value = dummy_response

        page, failure_reason = await fetcher._fetch_with_fallback("https://example.com/remote")

        assert page is not None
        assert failure_reason is None
        assert page.title == "Remote Title"
        assert page.extraction_method == "article_extractor_fallback"
        fetcher.session.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_page_uses_fallback_when_primary_missing(self, monkeypatch):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.fallback_extractor_enabled = True
        settings.fallback_extractor_endpoint = "http://fallback.local"
        settings.fallback_extractor_max_retries = 0

        fetcher = doc_fetcher.AsyncDocFetcher(settings)
        fetcher.playwright_fetcher = None  # Force fallback path
        fetcher.session = AsyncMock()

        dummy_response = SimpleNamespace(
            status=200,
            json=AsyncMock(
                return_value={
                    "title": "Remote",
                    "markdown": "# Remote\n\nBody",
                }
            ),
            text=AsyncMock(return_value=""),
        )
        fetcher.session.post.return_value = dummy_response

        result = await fetcher.fetch_page("https://example.com/fallback")

        assert result is not None
        assert result.extraction_method == "article_extractor_fallback"

    @pytest.mark.asyncio
    async def test_fallback_logs_failure_after_retries(self, caplog):
        doc_fetcher = _import_doc_fetcher()
        settings = _create_mock_settings()
        settings.fallback_extractor_enabled = True
        settings.fallback_extractor_endpoint = "http://fallback.local"
        settings.fallback_extractor_max_retries = 0

        fetcher = doc_fetcher.AsyncDocFetcher(settings)
        fetcher.session = AsyncMock()

        failing_response = SimpleNamespace(
            status=500,
            json=AsyncMock(return_value={}),
            text=AsyncMock(return_value="boom"),
        )
        fetcher.session.post.return_value = failing_response

        page, failure_reason = await fetcher._fetch_with_fallback("https://example.com/boom")

        assert page is None
        assert failure_reason == "status=500 body=boom"
        assert any("exhausted retries" in record.message for record in caplog.records)
