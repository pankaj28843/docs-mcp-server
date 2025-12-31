"""Unit tests for the models module."""

from datetime import datetime, timezone

from pydantic import ValidationError
import pytest

from docs_mcp_server.utils.models import (
    DocPage,
    FetchDocResponse,
    ReadabilityContent,
    SearchDocsResponse,
    SearchResult,
    SitemapEntry,
)


class TestReadabilityContent:
    """Test ReadabilityContent model."""

    def test_create_valid_readability_content(self):
        """Test creating valid ReadabilityContent."""
        content = ReadabilityContent(
            raw_html="<html><body><h1>Test</h1></body></html>",
            extracted_content="Test\nContent",
            processed_markdown="# Test\n\nContent",
            excerpt="Test excerpt",
            score=0.85,
            success=True,
            extraction_method="readability",
        )

        assert content.raw_html == "<html><body><h1>Test</h1></body></html>"
        assert content.extracted_content == "Test\nContent"
        assert content.processed_markdown == "# Test\n\nContent"
        assert content.excerpt == "Test excerpt"
        assert abs(content.score - 0.85) < 0.001
        assert content.success is True
        assert content.extraction_method == "readability"

    def test_readability_content_optional_score(self):
        """Test ReadabilityContent with optional score."""
        content = ReadabilityContent(
            raw_html="<html></html>",
            extracted_content="Content",
            processed_markdown="Content",
            excerpt="excerpt",
            success=False,
            extraction_method="fallback",
        )

        assert content.score is None
        assert content.success is False


class TestDocPage:
    """Test DocPage model."""

    def test_create_minimal_doc_page(self):
        """Test creating minimal DocPage."""
        page = DocPage(url="https://example.com/test", title="Test Page", content="Test content")

        assert page.url == "https://example.com/test"
        assert page.title == "Test Page"
        assert page.content == "Test content"
        assert page.extraction_method == "custom"
        assert page.readability_content is None

    def test_create_full_doc_page(self):
        """Test creating DocPage with all fields."""
        readability_content = ReadabilityContent(
            raw_html="<html><body><h1>Test</h1></body></html>",
            extracted_content="Test",
            processed_markdown="# Test",
            excerpt="Test excerpt",
            score=0.9,
            success=True,
            extraction_method="readability",
        )

        page = DocPage(
            url="https://example.com/test",
            title="Test Page",
            content="# Test\n\nContent",
            extraction_method="readability",
            readability_content=readability_content,
        )

        assert page.url == "https://example.com/test"
        assert page.title == "Test Page"
        assert page.content == "# Test\n\nContent"
        assert page.extraction_method == "readability"
        assert abs(page.readability_content.score - 0.9) < 0.001
        assert page.readability_content.excerpt == "Test excerpt"


class TestSearchResult:
    """Test SearchResult model."""

    def test_create_search_result(self):
        """Test creating SearchResult."""
        result = SearchResult(
            url="https://example.com/doc",
            title="Document Title",
            score=0.85,
            snippet="This is a snippet of the document content...",
        )

        assert result.url == "https://example.com/doc"
        assert result.title == "Document Title"
        assert abs(result.score - 0.85) < 0.001
        assert result.snippet == "This is a snippet of the document content..."

    def test_search_result_validation(self):
        """Test SearchResult validation."""
        # Test that all fields are required
        with pytest.raises(ValidationError):
            SearchResult()


class TestSearchDocsResponse:
    """Test SearchDocsResponse model."""

    def test_create_empty_search_response(self):
        """Test creating empty SearchDocsResponse."""
        response = SearchDocsResponse()

        assert response.results == []
        assert response.error is None
        assert response.query is None

    def test_create_search_response_with_results(self):
        """Test creating SearchDocsResponse with results."""
        results = [
            SearchResult(url="https://example.com/doc1", title="Doc 1", score=0.9, snippet="First document"),
            SearchResult(url="https://example.com/doc2", title="Doc 2", score=0.8, snippet="Second document"),
        ]

        response = SearchDocsResponse(results=results)

        assert len(response.results) == 2
        assert response.results[0].title == "Doc 1"
        assert response.results[1].title == "Doc 2"

    def test_create_search_response_with_error(self):
        """Test creating SearchDocsResponse with error."""
        response = SearchDocsResponse(results=[], error="Search failed", query="test query")

        assert response.results == []
        assert response.error == "Search failed"
        assert response.query == "test query"


class TestFetchDocResponse:
    """Test FetchDocResponse model."""

    def test_create_successful_fetch_response(self):
        """Test creating successful FetchDocResponse."""
        response = FetchDocResponse(
            url="https://example.com/doc",
            title="Document Title",
            content="# Document\n\nThis is the full document content.",
        )

        assert response.url == "https://example.com/doc"
        assert response.title == "Document Title"
        assert response.content == "# Document\n\nThis is the full document content."
        assert response.error is None

    def test_create_failed_fetch_response(self):
        """Test creating failed FetchDocResponse."""
        response = FetchDocResponse(url="https://example.com/doc", title="", content="", error="Document not found")

        assert response.url == "https://example.com/doc"
        assert response.title == ""
        assert response.content == ""
        assert response.error == "Document not found"

    def test_fetch_response_validation(self):
        """Test FetchDocResponse validation."""
        # Test that required fields must be provided
        with pytest.raises(ValidationError):
            FetchDocResponse()


class TestSitemapEntry:
    """Test SitemapEntry model."""

    def test_create_sitemap_entry_with_date(self):
        """Test creating SitemapEntry with lastmod date."""
        lastmod = datetime.now(timezone.utc)
        entry = SitemapEntry(url="https://example.com/doc", lastmod=lastmod)

        assert str(entry.url) == "https://example.com/doc"
        assert entry.lastmod == lastmod

    def test_create_sitemap_entry_without_date(self):
        """Test creating SitemapEntry without lastmod date."""
        entry = SitemapEntry(url="https://example.com/doc")

        assert str(entry.url) == "https://example.com/doc"
        assert entry.lastmod is None

    def test_sitemap_entry_url_validation(self):
        """Test SitemapEntry URL validation."""
        # Test invalid URL
        with pytest.raises(ValidationError):
            SitemapEntry(url="not-a-url")
