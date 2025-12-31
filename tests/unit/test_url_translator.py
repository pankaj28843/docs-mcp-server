"""Unit tests for the UrlTranslator service."""

import hashlib
from pathlib import Path

import pytest

from docs_mcp_server.utils.url_translator import UrlTranslator


pytestmark = pytest.mark.unit


@pytest.fixture
def url_translator(tmp_path: Path) -> UrlTranslator:
    """Fixture to create a UrlTranslator instance with a temporary data directory."""
    return UrlTranslator(tenant_data_dir=tmp_path)


def test_get_internal_path_from_public_url(url_translator: UrlTranslator):
    """Test resolving an internal path from a public URL."""
    public_url = "https://example.com/docs/page2/"  # Add trailing slash
    url_hash = hashlib.sha256(public_url.encode("utf-8")).hexdigest()
    expected_path = url_translator.tenant_data_dir / f"{url_hash}.md"

    internal_path = url_translator.get_internal_path_from_public_url(public_url)

    assert internal_path == expected_path


def test_get_internal_path_from_public_url_with_query_and_fragment(url_translator: UrlTranslator):
    """Test that rg query param and fragments are stripped, but other query params are preserved."""
    # The canonical URL will have query param preserved, but fragment stripped, and trailing slash added
    canonical_url = "https://example.com/docs/page2/?query=param"
    url_with_stuff = "https://example.com/docs/page2?query=param#L100"
    url_hash = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
    expected_path = url_translator.tenant_data_dir / f"{url_hash}.md"

    internal_path = url_translator.get_internal_path_from_public_url(url_with_stuff)

    assert internal_path == expected_path
