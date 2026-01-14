"""Additional unit tests for snippet helpers."""

import pytest

from docs_mcp_server.search.snippet import build_smart_snippet, highlight_terms_in_snippet


@pytest.mark.unit
def test_highlight_terms_no_matches_returns_original():
    snippet = "no matches here"
    result = highlight_terms_in_snippet(snippet, terms=["missing"])

    assert result == snippet


@pytest.mark.unit
def test_highlight_terms_skips_protected_regions():
    snippet = "[link](https://example.com)"
    result = highlight_terms_in_snippet(snippet, terms=["link"])

    assert result == snippet


@pytest.mark.unit
def test_build_smart_snippet_skips_empty_terms():
    text = "Searchable content here"
    snippet = build_smart_snippet(text, terms=["", "content"])

    assert "content" in snippet
