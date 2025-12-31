"""Unit tests for UrlTranslator.

Tests the hash-based translation logic that maps external URLs to
internal filesystem paths.
"""

import hashlib
from pathlib import Path

import pytest

from docs_mcp_server.utils.url_translator import UrlTranslator


pytestmark = pytest.mark.unit


class TestUrlTranslatorInit:
    """Tests for UrlTranslator initialization."""

    def test_init_with_valid_path(self, tmp_path: Path):
        """Test initialization with a valid tenant data directory."""
        translator = UrlTranslator(tmp_path)
        assert translator.tenant_data_dir == tmp_path

    def test_init_accepts_path_object(self, tmp_path: Path):
        """Test that initialization accepts Path objects."""
        translator = UrlTranslator(tmp_path / "subdir")
        assert isinstance(translator.tenant_data_dir, Path)


class TestGetInternalPathFromPublicUrl:
    """Tests for get_internal_path_from_public_url method."""

    @pytest.fixture
    def translator(self, tmp_path: Path) -> UrlTranslator:
        """Create a translator with a temporary data directory."""
        return UrlTranslator(tmp_path)

    def test_basic_url_returns_hashed_path(self, translator: UrlTranslator, tmp_path: Path):
        """Test that a basic URL returns a deterministic hashed path."""
        url = "https://example.com/docs/page.html"
        result = translator.get_internal_path_from_public_url(url)

        # Verify it's a path in the tenant data directory
        assert result.parent == tmp_path
        # Verify it has .md extension
        assert result.suffix == ".md"
        # Verify the filename is a sha256 hash (64 hex chars)
        assert len(result.stem) == 64
        assert all(c in "0123456789abcdef" for c in result.stem)

    def test_url_with_fragment_stripped(self, translator: UrlTranslator):
        """Test that URL fragments are stripped for canonical hashing."""
        url_with_fragment = "https://example.com/docs/page.html#section"
        url_without_fragment = "https://example.com/docs/page.html"

        result_with = translator.get_internal_path_from_public_url(url_with_fragment)
        result_without = translator.get_internal_path_from_public_url(url_without_fragment)

        # Both should produce the same path since fragment is stripped
        assert result_with == result_without

    def test_rg_query_param_stripped(self, translator: UrlTranslator):
        """Test that 'rg' query parameter is stripped for canonical hashing."""
        url_with_rg = "https://example.com/docs/page.html?rg=abc123"
        url_without_rg = "https://example.com/docs/page.html"

        result_with = translator.get_internal_path_from_public_url(url_with_rg)
        result_without = translator.get_internal_path_from_public_url(url_without_rg)

        assert result_with == result_without

    def test_other_query_params_preserved(self, translator: UrlTranslator):
        """Test that non-rg query parameters affect the hash."""
        url_no_query = "https://example.com/docs/page.html"
        url_with_query = "https://example.com/docs/page.html?version=2"

        result_no_query = translator.get_internal_path_from_public_url(url_no_query)
        result_with_query = translator.get_internal_path_from_public_url(url_with_query)

        # Different query params should produce different paths
        assert result_no_query != result_with_query

    def test_query_params_sorted_for_determinism(self, translator: UrlTranslator):
        """Test that query parameters are sorted to produce deterministic hashes."""
        url_a_first = "https://example.com/docs/page.html?a=1&b=2"
        url_b_first = "https://example.com/docs/page.html?b=2&a=1"

        result_a = translator.get_internal_path_from_public_url(url_a_first)
        result_b = translator.get_internal_path_from_public_url(url_b_first)

        # Should produce the same hash regardless of param order
        assert result_a == result_b

    def test_trailing_slash_normalization_for_directories(self, translator: UrlTranslator):
        """Test that directory URLs are normalized with trailing slash."""
        url_with_slash = "https://example.com/docs/"
        url_without_slash = "https://example.com/docs"

        result_with = translator.get_internal_path_from_public_url(url_with_slash)
        result_without = translator.get_internal_path_from_public_url(url_without_slash)

        # Both should produce the same path (trailing slash added)
        assert result_with == result_without

    def test_file_extension_urls_no_trailing_slash(self, translator: UrlTranslator):
        """Test that URLs with file extensions don't get trailing slash added."""
        url_html = "https://example.com/docs/page.html"

        result = translator.get_internal_path_from_public_url(url_html)

        # Compute expected hash manually
        expected_canonical = "https://example.com/docs/page.html"
        expected_hash = hashlib.sha256(expected_canonical.encode("utf-8")).hexdigest()

        assert result.stem == expected_hash

    def test_different_file_extensions_detected(self, translator: UrlTranslator):
        """Test that various file extensions are detected correctly."""
        extensions = [".html", ".pdf", ".txt", ".json", ".xml"]
        for ext in extensions:
            url = f"https://example.com/docs/file{ext}"
            result = translator.get_internal_path_from_public_url(url)
            # URL should NOT have trailing slash added (has extension)
            expected_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
            assert result.stem == expected_hash, f"Failed for extension {ext}"

    def test_url_scheme_preserved(self, translator: UrlTranslator):
        """Test that different URL schemes produce different hashes."""
        http_url = "http://example.com/docs/"
        https_url = "https://example.com/docs/"

        result_http = translator.get_internal_path_from_public_url(http_url)
        result_https = translator.get_internal_path_from_public_url(https_url)

        # Different schemes should produce different paths
        assert result_http != result_https

    def test_empty_path_normalized(self, translator: UrlTranslator):
        """Test URL with empty path."""
        url = "https://example.com"
        result = translator.get_internal_path_from_public_url(url)

        # Should work without error
        assert result.parent == translator.tenant_data_dir
        assert result.suffix == ".md"


class TestUrlTranslatorRoundTrip:
    """Test bidirectional translation maintains consistency."""

    @pytest.fixture
    def translator(self, tmp_path: Path) -> UrlTranslator:
        """Create a translator with a temporary data directory."""
        return UrlTranslator(tmp_path)

    def test_internal_path_deterministic(self, translator: UrlTranslator):
        """Test that same URL always produces same internal path."""
        url = "https://example.com/docs/page.html"

        result1 = translator.get_internal_path_from_public_url(url)
        result2 = translator.get_internal_path_from_public_url(url)

        assert result1 == result2


class TestEdgeCases:
    """Test edge cases and special URL patterns."""

    @pytest.fixture
    def translator(self, tmp_path: Path) -> UrlTranslator:
        """Create a translator with a temporary data directory."""
        return UrlTranslator(tmp_path)

    def test_url_with_unicode(self, translator: UrlTranslator):
        """Test URL with unicode characters."""
        url = "https://example.com/docs/页面.html"
        result = translator.get_internal_path_from_public_url(url)
        assert result.suffix == ".md"

    def test_url_with_special_chars_in_path(self, translator: UrlTranslator):
        """Test URL with special characters in path."""
        url = "https://example.com/docs/page%20name.html"
        result = translator.get_internal_path_from_public_url(url)
        assert result.suffix == ".md"

    def test_url_with_port_number(self, translator: UrlTranslator):
        """Test URL with explicit port number."""
        url = "https://example.com:8080/docs/page.html"
        result = translator.get_internal_path_from_public_url(url)
        assert result.suffix == ".md"

    def test_url_with_authentication(self, translator: UrlTranslator):
        """Test URL with user:pass authentication."""
        url = "https://user:pass@example.com/docs/page.html"
        result = translator.get_internal_path_from_public_url(url)
        assert result.suffix == ".md"

    def test_very_long_url(self, translator: UrlTranslator):
        """Test very long URL still produces fixed-length hash."""
        long_path = "/".join(["segment"] * 100)
        url = f"https://example.com/{long_path}/page.html"
        result = translator.get_internal_path_from_public_url(url)

        # Hash should always be 64 characters regardless of URL length
        assert len(result.stem) == 64

    def test_url_path_ending_with_slash_and_extension(self, translator: UrlTranslator):
        """Test URL with extension followed by slash (unusual but valid)."""
        url = "https://example.com/docs/page.html/"
        result = translator.get_internal_path_from_public_url(url)
        assert result.suffix == ".md"

    def test_empty_query_string(self, translator: UrlTranslator):
        """Test URL with empty query string (just ?)."""
        url = "https://example.com/docs/page.html?"
        result = translator.get_internal_path_from_public_url(url)
        assert result.suffix == ".md"

    def test_multiple_rg_params_stripped(self, translator: UrlTranslator):
        """Test that multiple rg params are all stripped."""
        url = "https://example.com/docs/page.html?rg=abc&rg=def&other=keep"
        result = translator.get_internal_path_from_public_url(url)

        # The 'other' param should still affect hash
        url_no_rg = "https://example.com/docs/page.html?other=keep"
        result_no_rg = translator.get_internal_path_from_public_url(url_no_rg)

        assert result == result_no_rg
