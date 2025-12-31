from pathlib import Path

import pytest

from docs_mcp_server.adapters.search_repository import AbstractSearchRepository
from docs_mcp_server.domain.search import MatchTrace, SearchResponse, SearchResult
from docs_mcp_server.service_layer.search_service import SearchService


class _FakeSearchRepository(AbstractSearchRepository):
    def __init__(self, response: SearchResponse):
        self.response = response
        self.calls: list[tuple[object, Path, int, bool, bool]] = []

    async def search_documents(
        self,
        query,
        data_dir: Path,
        max_results: int = 20,
        word_match: bool = False,
        include_stats: bool = False,
    ) -> SearchResponse:
        self.calls.append((query, data_dir, max_results, word_match, include_stats))
        return self.response


def _make_search_result() -> SearchResult:
    return SearchResult(
        document_url="file:///tmp/docs/guide.md",
        document_title="Guide",
        snippet="context",
        match_trace=MatchTrace(
            stage=1,
            stage_name="exact",
            query_variant="guide",
            match_reason="Exact match",
            ripgrep_flags=["--fixed-strings"],
        ),
        relevance_score=0.9,
    )


@pytest.mark.unit
class TestSearchService:
    @pytest.mark.asyncio
    async def test_forwards_analyzed_query_and_options(self):
        response = SearchResponse(results=[_make_search_result()], stats=None)
        repository = _FakeSearchRepository(response)
        service = SearchService(search_repository=repository)
        query_text = "GraphQL docs"
        data_dir = Path("/tmp/docs")

        result = await service.search(
            raw_query=query_text,
            data_dir=data_dir,
            max_results=5,
            word_match=True,
            include_stats=True,
            tenant_context="django",
        )

        assert result is response
        assert len(repository.calls) == 1
        analyzed_query, recorded_dir, recorded_limit, recorded_word_match, recorded_stats = repository.calls[0]
        assert analyzed_query.original_text == query_text
        assert analyzed_query.tenant_context == "django"
        assert recorded_dir == data_dir
        assert recorded_limit == 5
        assert recorded_word_match is True
        assert recorded_stats is True

    @pytest.mark.asyncio
    async def test_handles_empty_results_without_errors(self):
        repository = _FakeSearchRepository(SearchResponse(results=[], stats=None))
        service = SearchService(search_repository=repository)

        result = await service.search(raw_query="nothing matches", data_dir=Path("/tmp/docs"))

        assert result.results == []
        assert len(repository.calls) == 1
