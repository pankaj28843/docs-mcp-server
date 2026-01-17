"""Tests for the BM25-backed indexed search repository."""

from __future__ import annotations

import time

import pytest

from docs_mcp_server.adapters.indexed_search_repository import IndexedSearchRepository
from docs_mcp_server.deployment_config import SearchBoostConfig, SearchRankingConfig, SearchSnippetConfig
from docs_mcp_server.domain.search import KeywordSet, SearchQuery
from docs_mcp_server.search.schema import create_default_schema
from docs_mcp_server.search.sqlite_storage import SqliteSegmentStore, SqliteSegmentWriter


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_indexed_repository_returns_ranked_results(tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SqliteSegmentWriter(schema)
    writer.add_document(
        {
            "url": "https://example.com/teams/bots",
            "title": "Build Teams bots",
            "headings": "Bots\nIntegrations",
            "body": "Use incoming webhooks to integrate external services with Microsoft Teams bots.",
            "path": "teams/bots.md",
            "tags": ["teams", "bots"],
            "excerpt": "Build webhook integrations",
            "timestamp": 1700000000,
        }
    )
    writer.add_document(
        {
            "url": "https://example.com/graph/auth",
            "title": "Graph authentication",
            "headings": "OAuth",
            "body": "Authenticate against Microsoft Graph by exchanging OAuth tokens.",
            "path": "graph/auth.md",
            "tags": ["graph"],
            "excerpt": "OAuth and Graph",
            "timestamp": 1700000001,
        }
    )
    store = SqliteSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    query = SearchQuery(
        original_text="Teams webhook integration",
        normalized_tokens=["teams", "webhook", "integration"],
        extracted_keywords=KeywordSet(technical_terms=["Teams webhook integration"]),
    )

    response = await repository.search_documents(query, docs_root, max_results=5, include_stats=True)

    assert response.results, "Expected at least one ranked result"
    assert response.results[0].document_url.endswith("bots"), "Webhook doc should rank first"
    assert response.results[0].relevance_score >= response.results[-1].relevance_score
    assert "[[" in response.results[0].snippet or "<mark>" in response.results[0].snippet
    assert response.stats is not None
    assert response.stats.stage == 5


@pytest.mark.asyncio
async def test_indexed_repository_handles_missing_segments(tmp_path):
    docs_root = tmp_path / "tenant"
    docs_root.mkdir(parents=True)

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )
    query = SearchQuery(original_text="missing", normalized_tokens=[], extracted_keywords=KeywordSet())

    response = await repository.search_documents(query, docs_root, max_results=5)

    assert response.results == []
    assert response.stats is None


@pytest.mark.asyncio
async def test_search_p95_budget(tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SqliteSegmentWriter(schema)
    for idx in range(200):
        writer.add_document(
            {
                "url": f"https://example.com/doc/{idx}",
                "title": f"Doc {idx}",
                "body": "Search performance budget with repeated terms.",
                "path": f"doc/{idx}.md",
                "tags": ["perf", "budget"],
                "excerpt": "Perf budget example",
                "timestamp": 1700000000 + idx,
            }
        )
    store = SqliteSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )
    query = SearchQuery(original_text="performance budget", normalized_tokens=[], extracted_keywords=KeywordSet())

    timings = []
    for _ in range(25):
        start = time.perf_counter()
        await repository.search_documents(query, docs_root, max_results=10)
        timings.append((time.perf_counter() - start) * 1000)

    timings.sort()
    p95 = timings[int(0.95 * (len(timings) - 1))]
    assert p95 < 250.0, f"Search p95 too slow: {p95:.2f}ms"
