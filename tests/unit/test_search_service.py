from pathlib import Path

import pytest

from docs_mcp_server.adapters.search_repository import AbstractSearchRepository
from docs_mcp_server.domain.search import MatchTrace, SearchResponse, SearchResult
from docs_mcp_server.service_layer.search_service import SearchService


class _FakeSearchRepository(AbstractSearchRepository):
    def __init__(self, response: SearchResponse):
        self.response = response
        self.calls: list[tuple[object, Path, int, bool, bool]] = []
        self.invalidated: list[Path | None] = []
        self.warm_calls: list[Path] = []

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

    async def warm_cache(self, data_dir: Path) -> None:
        self.warm_calls.append(data_dir)

    def invalidate_cache(self, data_dir: Path | None = None) -> None:
        self.invalidated.append(data_dir)


class _RepoWithMetrics(_FakeSearchRepository):
    def __init__(self, response: SearchResponse):
        super().__init__(response)
        self.metrics_calls: list[Path] = []

    def get_cache_metrics(self, data_dir: Path) -> dict[str, dict[str, float | int]]:
        self.metrics_calls.append(data_dir)
        return {"demo": {"hits": 1, "misses": 0, "loads": 1, "last_load_seconds": 0.01}}


class _RepoWithResidency(_FakeSearchRepository):
    def __init__(self, response: SearchResponse):
        super().__init__(response)
        self.ensure_calls: list[tuple[Path, float | None]] = []
        self.stop_calls: list[Path | None] = []

    async def ensure_resident(self, data_dir: Path, *, poll_interval: float | None = None) -> None:
        self.ensure_calls.append((data_dir, poll_interval))

    async def stop_resident(self, data_dir: Path | None = None) -> None:
        self.stop_calls.append(data_dir)


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

    @pytest.mark.asyncio
    async def test_search_reads_cache_metrics_when_available(self):
        response = SearchResponse(results=[_make_search_result()], stats=None)
        repository = _RepoWithMetrics(response)
        service = SearchService(search_repository=repository)

        await service.search(raw_query="docs", data_dir=Path("/tmp/docs"))

        assert repository.metrics_calls == [Path("/tmp/docs")]

    @pytest.mark.asyncio
    async def test_warm_index_forwards_to_repository(self):
        repository = _FakeSearchRepository(SearchResponse(results=[], stats=None))
        service = SearchService(search_repository=repository)
        data_dir = Path("/tmp/docs")

        await service.warm_index(data_dir)

        assert repository.warm_calls == [data_dir]

    @pytest.mark.asyncio
    async def test_ensure_resident_prefers_repository_api(self):
        repository = _RepoWithResidency(SearchResponse(results=[], stats=None))
        service = SearchService(search_repository=repository)
        data_dir = Path("/tmp/docs")

        await service.ensure_resident(data_dir, poll_interval=0.2)

        assert repository.ensure_calls == [(data_dir, 0.2)]

    @pytest.mark.asyncio
    async def test_ensure_resident_falls_back_to_warm_index(self):
        repository = _FakeSearchRepository(SearchResponse(results=[], stats=None))
        service = SearchService(search_repository=repository)
        data_dir = Path("/tmp/docs")

        await service.ensure_resident(data_dir)

        assert repository.warm_calls == [data_dir]

    def test_invalidate_cache_forwards(self):
        repository = _FakeSearchRepository(SearchResponse(results=[], stats=None))
        service = SearchService(search_repository=repository)

        service.invalidate_cache(Path("/tmp/docs"))

        assert repository.invalidated == [Path("/tmp/docs")]

    @pytest.mark.asyncio
    async def test_stop_resident_uses_repository_api(self):
        repository = _RepoWithResidency(SearchResponse(results=[], stats=None))
        service = SearchService(search_repository=repository)

        await service.stop_resident(Path("/tmp/docs"))

        assert repository.stop_calls == [Path("/tmp/docs")]

    @pytest.mark.asyncio
    async def test_stop_resident_falls_back_to_cache_invalidation(self):
        repository = _FakeSearchRepository(SearchResponse(results=[], stats=None))
        service = SearchService(search_repository=repository)

        await service.stop_resident(Path("/tmp/docs"))

        assert repository.invalidated == [Path("/tmp/docs")]
