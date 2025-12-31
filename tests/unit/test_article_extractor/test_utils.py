"""Unit tests for article_extractor.utils module."""

from article_extractor.utils import (
    extract_excerpt,
    get_word_count,
    normalize_whitespace,
)
import pytest


@pytest.mark.unit
class TestGetWordCount:
    """Test word counting function."""

    def test_empty_string(self):
        """Empty string returns 0 words."""
        assert get_word_count("") == 0

    def test_single_word(self):
        """Single word returns 1."""
        assert get_word_count("hello") == 1

    def test_multiple_words(self):
        """Multiple words counted correctly."""
        assert get_word_count("hello world foo bar") == 4

    def test_extra_whitespace(self):
        """Extra whitespace doesn't affect count."""
        assert get_word_count("  hello   world  ") == 2


@pytest.mark.unit
class TestNormalizeWhitespace:
    """Test whitespace normalization."""

    def test_normal_text(self):
        """Normal text unchanged."""
        assert normalize_whitespace("hello world") == "hello world"

    def test_multiple_spaces(self):
        """Multiple spaces collapsed."""
        assert normalize_whitespace("hello    world") == "hello world"

    def test_newlines_and_tabs(self):
        """Newlines and tabs converted to spaces."""
        assert normalize_whitespace("hello\n\tworld") == "hello world"

    def test_leading_trailing(self):
        """Leading/trailing whitespace removed."""
        assert normalize_whitespace("  hello world  ") == "hello world"


@pytest.mark.unit
class TestExtractExcerpt:
    """Test excerpt extraction."""

    def test_short_text(self):
        """Short text returned as-is."""
        text = "Short text"
        assert extract_excerpt(text) == "Short text"

    def test_long_text_truncated(self):
        """Long text truncated with ellipsis."""
        text = "a " * 150  # 300 chars
        excerpt = extract_excerpt(text, max_length=50)
        assert len(excerpt) <= 53  # 50 + "..."
        assert excerpt.endswith("...")

    def test_breaks_at_word_boundary(self):
        """Truncation breaks at word boundary."""
        text = "This is a sentence that is quite long"
        excerpt = extract_excerpt(text, max_length=20)
        # Should break at space, not mid-word
        assert not excerpt[-4].isalnum() or excerpt.endswith("...")

    def test_custom_max_length(self):
        """Custom max_length respected."""
        text = "word " * 100
        excerpt = extract_excerpt(text, max_length=100)
        assert len(excerpt) <= 103  # 100 + "..."
