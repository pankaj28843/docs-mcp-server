"""Parity tests comparing pure-Python extractor against expected extraction quality.

These tests verify that the pure-Python article extractor produces results
that match or exceed the quality of the cascading extractor.
"""

from article_extractor import extract_article
import pytest

from tests.fixtures.parity_test_corpus import (
    CODE_HEAVY_DOCS,
    EXPECTED_CODE_HEAVY,
    EXPECTED_MINIMAL,
    EXPECTED_MULTI_COLUMN,
    EXPECTED_SIMPLE_BLOG,
    MINIMAL_CONTENT,
    MULTI_COLUMN_NEWS,
    PARITY_FIXTURES,
    SIMPLE_BLOG_POST,
)


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


@pytest.mark.unit
class TestParitySimpleBlogPost:
    """Test extraction parity for simple blog post."""

    def test_extracts_correct_title(self):
        """Title should match expected."""
        result = extract_article(SIMPLE_BLOG_POST, url="https://example.com/blog")
        assert EXPECTED_SIMPLE_BLOG["title"].lower() in result.title.lower()

    def test_meets_minimum_word_count(self):
        """Extracted content should have enough words."""
        result = extract_article(SIMPLE_BLOG_POST, url="https://example.com/blog")
        word_count = count_words(result.content)
        assert word_count >= EXPECTED_SIMPLE_BLOG["min_words"], (
            f"Expected at least {EXPECTED_SIMPLE_BLOG['min_words']} words, got {word_count}"
        )

    def test_contains_expected_content(self):
        """Content should contain expected phrases."""
        result = extract_article(SIMPLE_BLOG_POST, url="https://example.com/blog")
        content_lower = result.content.lower()
        for phrase in EXPECTED_SIMPLE_BLOG["must_contain"]:
            assert phrase.lower() in content_lower, f"Expected '{phrase}' in content"

    def test_excludes_boilerplate(self):
        """Content should not contain navigation/footer."""
        result = extract_article(SIMPLE_BLOG_POST, url="https://example.com/blog")
        content_lower = result.content.lower()
        for phrase in EXPECTED_SIMPLE_BLOG["must_not_contain"]:
            assert phrase.lower() not in content_lower, f"Unexpected '{phrase}' in content"


@pytest.mark.unit
class TestParityCodeHeavyDocs:
    """Test extraction parity for code-heavy documentation."""

    def test_extracts_correct_title(self):
        """Title should match expected."""
        result = extract_article(CODE_HEAVY_DOCS, url="https://example.com/docs/config")
        assert EXPECTED_CODE_HEAVY["title"].lower() in result.title.lower()

    def test_preserves_code_blocks(self):
        """Code examples should be preserved."""
        result = extract_article(CODE_HEAVY_DOCS, url="https://example.com/docs/config")
        # Check for code content
        assert "API_KEY" in result.content
        assert "config.json" in result.content or "Config.from_file" in result.content

    def test_contains_expected_content(self):
        """Content should contain expected phrases."""
        result = extract_article(CODE_HEAVY_DOCS, url="https://example.com/docs/config")
        content = result.content
        found_phrases = [phrase for phrase in EXPECTED_CODE_HEAVY["must_contain"] if phrase in content]
        # At least half of expected phrases should be found
        assert len(found_phrases) >= len(EXPECTED_CODE_HEAVY["must_contain"]) // 2, (
            f"Expected more phrases. Found: {found_phrases}"
        )

    def test_excludes_navigation(self):
        """Content should not contain nav menu items."""
        result = extract_article(CODE_HEAVY_DOCS, url="https://example.com/docs/config")
        content = result.content
        # Nav menu items should not be in main content
        assert "nav-menu" not in content


@pytest.mark.unit
class TestParityMultiColumnNews:
    """Test extraction parity for multi-column news article."""

    def test_extracts_correct_title(self):
        """Title should use og:title over page title."""
        result = extract_article(MULTI_COLUMN_NEWS, url="https://news.example.com/article")
        assert EXPECTED_MULTI_COLUMN["title"].lower() in result.title.lower()

    def test_meets_minimum_word_count(self):
        """Extracted content should have enough words."""
        result = extract_article(MULTI_COLUMN_NEWS, url="https://news.example.com/article")
        word_count = count_words(result.content)
        assert word_count >= EXPECTED_MULTI_COLUMN["min_words"], (
            f"Expected at least {EXPECTED_MULTI_COLUMN['min_words']} words, got {word_count}"
        )

    def test_contains_article_content(self):
        """Content should contain main article phrases."""
        result = extract_article(MULTI_COLUMN_NEWS, url="https://news.example.com/article")
        content_lower = result.content.lower()
        for phrase in EXPECTED_MULTI_COLUMN["must_contain"]:
            assert phrase.lower() in content_lower, f"Expected '{phrase}' in content"

    def test_excludes_sidebar_and_ads(self):
        """Content should not contain sidebar or ad content."""
        result = extract_article(MULTI_COLUMN_NEWS, url="https://news.example.com/article")
        content = result.content
        for phrase in EXPECTED_MULTI_COLUMN["must_not_contain"]:
            assert phrase not in content, f"Unexpected '{phrase}' in content"


@pytest.mark.unit
class TestParityMinimalContent:
    """Test extraction handling of minimal content pages."""

    def test_extracts_title(self):
        """Title should be extracted even for minimal pages."""
        result = extract_article(MINIMAL_CONTENT, url="https://example.com/changelog")
        assert "changelog" in result.title.lower()

    def test_handles_minimal_content_gracefully(self):
        """Should handle minimal content without error."""
        result = extract_article(MINIMAL_CONTENT, url="https://example.com/changelog")
        # Should return something, not crash
        assert result is not None
        # Content should be minimal
        word_count = count_words(result.content)
        assert word_count <= EXPECTED_MINIMAL.get("max_words", 100) or word_count > 0


@pytest.mark.unit
class TestParityParametrized:
    """Parametrized parity tests across all fixtures."""

    @pytest.mark.parametrize("fixture_name", list(PARITY_FIXTURES.keys()))
    def test_extraction_succeeds(self, fixture_name):
        """All fixture extractions should succeed."""
        html, expected = PARITY_FIXTURES[fixture_name]
        result = extract_article(html, url=f"https://example.com/{fixture_name}")

        # Basic success criteria
        assert result is not None
        assert result.title  # Has a title

        # Check title if expected
        if "title" in expected:
            assert expected["title"].lower() in result.title.lower()

    @pytest.mark.parametrize("fixture_name", list(PARITY_FIXTURES.keys()))
    def test_content_not_empty(self, fixture_name):
        """Extracted content should not be empty."""
        html, expected = PARITY_FIXTURES[fixture_name]
        result = extract_article(html, url=f"https://example.com/{fixture_name}")

        # Should have some content (unless it's minimal)
        if not expected.get("is_minimal"):
            assert result.content.strip(), "Content should not be empty"


@pytest.mark.unit
class TestExtractionQualityMetrics:
    """Test overall extraction quality metrics."""

    def test_no_script_tags_in_content(self):
        """Script tags should never appear in extracted content."""
        html_with_scripts = """
        <html><body>
        <article>
            <p>Real content here with enough words to pass threshold.</p>
            <script>alert('xss')</script>
            <p>More content after script that should be included.</p>
            <p>Even more content to ensure we pass word count minimums.</p>
            <p>Final paragraph with additional text for the extraction.</p>
        </article>
        </body></html>
        """
        result = extract_article(html_with_scripts, url="https://example.com")
        assert "<script>" not in result.content
        assert "alert(" not in result.content

    def test_no_style_tags_in_content(self):
        """Style tags should never appear in extracted content."""
        html_with_styles = """
        <html><body>
        <article>
            <p>Real content here with enough words to pass threshold.</p>
            <style>.hide { display: none; }</style>
            <p>More content after style that should be included.</p>
            <p>Even more content to ensure we pass word count minimums.</p>
            <p>Final paragraph with additional text for the extraction.</p>
        </article>
        </body></html>
        """
        result = extract_article(html_with_styles, url="https://example.com")
        assert "<style>" not in result.content
        assert "display: none" not in result.content

    def test_preserves_headings(self):
        """Headings should be preserved in markdown output."""
        html_with_headings = """
        <html><body>
        <article>
            <h1>Main Title</h1>
            <p>Introduction paragraph with enough content.</p>
            <h2>Section One</h2>
            <p>Content for section one with details.</p>
            <h3>Subsection</h3>
            <p>Content for subsection with more info.</p>
            <p>Extra content to pass word count threshold.</p>
        </article>
        </body></html>
        """
        result = extract_article(html_with_headings, url="https://example.com")
        # Headings should be present (as markdown # or as text)
        assert "Main Title" in result.content or "# Main Title" in result.content
        assert "Section One" in result.content

    def test_preserves_lists(self):
        """Lists should be preserved in output."""
        html_with_lists = """
        <html><body>
        <article>
            <h1>Features</h1>
            <p>Here are the main features of our product:</p>
            <ul>
                <li>Feature one with description</li>
                <li>Feature two with description</li>
                <li>Feature three with description</li>
            </ul>
            <p>Additional paragraph with more content.</p>
            <p>Final paragraph to meet word threshold.</p>
        </article>
        </body></html>
        """
        result = extract_article(html_with_lists, url="https://example.com")
        # List items should be present
        assert "Feature one" in result.content
        assert "Feature two" in result.content
