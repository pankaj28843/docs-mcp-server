"""Unit tests for model serialization defaults."""

import json

import pytest

from docs_mcp_server.utils.models import SearchDocsResponse, SearchResult


@pytest.mark.unit
def test_search_result_model_dump_excludes_none_by_default():
    result = SearchResult(url="https://example.com", title="Doc", score=1.0, snippet="hello")
    payload = result.model_dump()

    assert "match_stage" not in payload
    assert payload["url"] == "https://example.com"


@pytest.mark.unit
def test_search_result_model_dump_json_excludes_none_by_default():
    result = SearchResult(url="https://example.com", title="Doc", score=1.0, snippet="hello")
    payload = json.loads(result.model_dump_json())

    assert "match_reason" not in payload
    assert payload["title"] == "Doc"


@pytest.mark.unit
def test_search_docs_response_model_dump_excludes_none_by_default():
    response = SearchDocsResponse(results=[], error=None, query=None)
    payload = response.model_dump()

    assert "error" not in payload
    assert payload["results"] == []


@pytest.mark.unit
def test_search_docs_response_model_dump_json_excludes_none_by_default():
    response = SearchDocsResponse(results=[], error=None, query=None)
    payload = json.loads(response.model_dump_json())

    assert "stats" not in payload
    assert payload["results"] == []
