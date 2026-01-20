"""Unit tests for article_extractor.extractor module."""

from article_extractor import ArticleResult, extract_article
from justhtml import JustHTML
import pytest


@pytest.mark.unit
class TestExtractArticle:
    """Test main extraction function."""

    def test_extracts_title_from_og_title(self, simple_article_html: str):
        """Should extract title from og:title meta tag."""
        result = extract_article(simple_article_html, url="https://example.com/post")
        assert result.title == "Test Article Title"

    def test_returns_success_for_valid_html(self, simple_article_html: str):
        """Should return success=True for valid article HTML."""
        result = extract_article(simple_article_html)
        assert result.success is True
        assert result.error is None

    def test_returns_markdown_content(self, simple_article_html: str):
        """Should return markdown version of content."""
        result = extract_article(simple_article_html)
        assert result.markdown  # Non-empty
        assert isinstance(result.markdown, str)

    def test_returns_word_count(self, simple_article_html: str):
        """Should return word count of extracted content."""
        result = extract_article(simple_article_html)
        assert result.word_count > 0

    def test_returns_excerpt(self, simple_article_html: str):
        """Should return excerpt from content."""
        result = extract_article(simple_article_html)
        assert result.excerpt  # Non-empty
        assert len(result.excerpt) <= 203  # 200 + "..."

    def test_handles_minimal_html(self, minimal_html: str):
        """Should handle minimal HTML without crashing."""
        result = extract_article(minimal_html)
        # May fail due to insufficient content, but should not crash
        assert isinstance(result, ArticleResult)

    def test_extracts_code_heavy_content(self, code_heavy_html: str):
        """Should extract content from code-heavy documentation."""
        result = extract_article(code_heavy_html)
        assert result.success is True
        assert "pip install" in result.markdown or "pip install" in result.content

    def test_filters_navigation(self, navigation_heavy_html: str):
        """Should filter out heavy navigation, keep main content."""
        result = extract_article(navigation_heavy_html)
        assert result.success is True
        # Main content should be present
        assert "Main Article" in result.title or "Main Article" in result.content

    def test_handles_bytes_input(self, simple_article_html: str):
        """Should handle bytes input (UTF-8)."""
        html_bytes = simple_article_html.encode("utf-8")
        result = extract_article(html_bytes)
        assert result.success is True

    def test_handles_invalid_html(self):
        """Should handle invalid/broken HTML gracefully."""
        broken_html = "<html><body><p>Unclosed paragraph<div>Mixed content"
        result = extract_article(broken_html)
        # Should not crash - JustHTML is tolerant
        assert isinstance(result, ArticleResult)


@pytest.mark.unit
class TestExtractTitle:
    """Test title extraction specifically."""

    def test_og_title_priority(self):
        """og:title should take priority over <title>."""
        html = """
        <html>
        <head>
            <title>Regular Title | Site</title>
            <meta property="og:title" content="OG Title">
        </head>
        <body><p>Content here</p></body>
        </html>
        """
        result = extract_article(html)
        assert result.title == "OG Title"

    def test_title_fallback(self):
        """Should fall back to <title> if no og:title or h1."""
        html = """
        <html>
        <head>
            <title>Site Name | Page Title</title>
        </head>
        <body><p>Content here with enough words to pass threshold.</p></body>
        </html>
        """
        result = extract_article(html)
        # Takes last segment after "|" as page title
        assert "Page Title" in result.title

    def test_h1_fallback(self):
        """Should fall back to h1 if no title tag."""
        html = """
        <html>
        <body>
            <h1>H1 Title Here</h1>
            <p>Content here with enough words to pass the minimum threshold.</p>
        </body>
        </html>
        """
        result = extract_article(html)
        assert result.title == "H1 Title Here"

    def test_url_fallback(self):
        """Should use URL for title if nothing else available."""
        html = "<html><body><p>Just content, no title anywhere.</p></body></html>"
        result = extract_article(html, url="https://example.com/my-article-page")
        # Should derive from URL path
        assert "My Article Page" in result.title or "Untitled" in result.title


# NOTE: TestArticleResultCompatibility tests removed - to_extraction_result()
# is no longer part of the standalone article_extractor package.
# The conversion is now done in cascading_html_extractor.py directly.


@pytest.mark.unit
class TestJustHTMLInstalled:
    """Verify JustHTML is correctly installed and working."""

    def test_justhtml_import(self):
        """JustHTML should be importable."""
        assert JustHTML is not None

    def test_justhtml_basic_parsing(self):
        """JustHTML should parse basic HTML."""
        doc = JustHTML("<p>Hello World</p>")
        ps = doc.query("p")
        assert len(ps) == 1
        assert ps[0].to_text() == "Hello World"

    def test_justhtml_to_markdown(self):
        """JustHTML should convert to markdown."""
        doc = JustHTML("<h1>Title</h1><p>Paragraph text here.</p>")
        md = doc.to_markdown()
        assert "Title" in md
        assert "Paragraph" in md

    def test_justhtml_css_selectors(self):
        """JustHTML should support CSS selectors."""
        html = '<div class="content"><p id="first">First</p><p>Second</p></div>'
        doc = JustHTML(html)

        # Class selector
        content = doc.query(".content")
        assert len(content) == 1

        # ID selector
        first = doc.query("#first")
        assert len(first) == 1
        assert first[0].to_text() == "First"

        # Descendant selector
        ps = doc.query(".content p")
        assert len(ps) == 2
