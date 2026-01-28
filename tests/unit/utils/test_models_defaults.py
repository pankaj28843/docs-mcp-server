"""Unit tests for model serialization defaults."""

import json

import pytest

from docs_mcp_server.utils.models import SearchDocsResponse, SearchResult


@pytest.mark.unit
def test_search_result_model_dump():
    result = SearchResult(url="https://example.com", title="Doc", snippet="hello")
    payload = result.model_dump()

    assert payload["url"] == "https://example.com"
    assert payload["title"] == "Doc"
    assert payload["snippet"] == "hello"


@pytest.mark.unit
def test_search_result_model_dump_json():
    result = SearchResult(url="https://example.com", title="Doc", snippet="hello")
    payload = json.loads(result.model_dump_json())

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
