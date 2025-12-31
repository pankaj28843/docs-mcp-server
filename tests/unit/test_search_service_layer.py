"""Unit tests for the high-level SearchService orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from docs_mcp_server.domain.search import (
    KeywordSet,
    MatchTrace,
    SearchQuery,
    SearchResponse,
    SearchResult,
)
from docs_mcp_server.service_layer.search_service import SearchService


class DummyAnalyzer:
    """Records analyze calls and returns a fixed SearchQuery."""

    def __init__(self, result: SearchQuery) -> None:
        self.result = result
        self.calls: list[tuple[str, str | None]] = []

    def analyze(self, raw_query: str, tenant_context: str | None) -> SearchQuery:
        self.calls.append((raw_query, tenant_context))
        return self.result


class FakeSearchRepository:
    """Captures search_documents invocations for assertion."""

    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.calls: list[tuple[SearchQuery, Path, int, bool, bool]] = []

    async def search_documents(
        self,
        analyzed_query: SearchQuery,
        data_dir: Path,
        max_results: int,
        word_match: bool,
        include_stats: bool,
    ) -> SearchResponse:
        self.calls.append((analyzed_query, data_dir, max_results, word_match, include_stats))
        return self.response


def _build_search_query() -> SearchQuery:
    return SearchQuery(
        original_text="install django",
        normalized_tokens=["install", "django"],
        extracted_keywords=KeywordSet(technical_terms=["install django"]),
        tenant_context="django",
    )


def _build_search_result() -> SearchResult:
    return SearchResult(
        document_url="https://docs.example.com/install",
        document_title="Install",
        snippet="Use pip to install",
        match_trace=MatchTrace(
            stage=1,
            stage_name="keywords",
            query_variant="install django",
            match_reason="technical term",
        ),
        relevance_score=0.9,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_executes_analyzer_and_repository(tmp_path: Path) -> None:
    response = SearchResponse(results=[_build_search_result()])
    repo = FakeSearchRepository(response)
    service = SearchService(search_repository=repo)
    analyzer = DummyAnalyzer(_build_search_query())
    service.query_analyzer = analyzer

    result = await service.search(
        raw_query="Install Django",
        data_dir=tmp_path,
        max_results=5,
        word_match=True,
        include_stats=True,
        tenant_context="django",
    )

    assert result is response
    assert analyzer.calls == [("Install Django", "django")]
    assert repo.calls == [(analyzer.result, tmp_path, 5, True, True)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_handles_empty_results(tmp_path: Path) -> None:
    response = SearchResponse(results=[])
    repo = FakeSearchRepository(response)
    service = SearchService(search_repository=repo)
    analyzer = DummyAnalyzer(_build_search_query())
    service.query_analyzer = analyzer

    result = await service.search(raw_query="missing", data_dir=tmp_path)

    assert result.results == []
    assert repo.calls[0][2:] == (20, False, False)
    assert analyzer.calls == [("missing", None)]
