"""Additional unit tests for analyzers."""

import pytest

from docs_mcp_server.search.analyzers import KeywordAnalyzer


@pytest.mark.unit
def test_keyword_analyzer_empty_text_returns_empty():
    analyzer = KeywordAnalyzer()
    assert analyzer("") == []
