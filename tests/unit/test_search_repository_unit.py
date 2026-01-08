from __future__ import annotations

from pathlib import Path

import pytest

from docs_mcp_server.adapters.search_repository import AbstractSearchRepository
from docs_mcp_server.domain.search import SearchQuery, SearchResponse


class DummySearchRepository(AbstractSearchRepository):
    async def search_documents(
        self,
        query: SearchQuery,
        data_dir: Path,
        max_results: int = 20,
        word_match: bool = False,
        include_stats: bool = False,
    ) -> SearchResponse:
        return SearchResponse(results=[], stats=None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_repository_default_hooks(tmp_path: Path) -> None:
    repo = DummySearchRepository()
    query = SearchQuery(original_text="demo")

    await repo.search_documents(query, tmp_path)
    await repo.warm_cache(tmp_path)
    repo.invalidate_cache(tmp_path)
    assert await repo.reload_cache(tmp_path) is False
    assert repo.get_cache_metrics(tmp_path) == {}
