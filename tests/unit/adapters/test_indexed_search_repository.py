"""Tests for the BM25-backed indexed search repository."""

from __future__ import annotations

import asyncio

import pytest

from docs_mcp_server.adapters import indexed_search_repository as indexed_repo_module
from docs_mcp_server.adapters.indexed_search_repository import IndexedSearchRepository
from docs_mcp_server.deployment_config import SearchBoostConfig, SearchRankingConfig, SearchSnippetConfig
from docs_mcp_server.domain.search import KeywordSet, SearchQuery
from docs_mcp_server.search.schema import create_default_schema
from docs_mcp_server.search.storage import JsonSegmentStore, SegmentWriter


@pytest.mark.asyncio
async def test_indexed_repository_returns_ranked_results(tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SegmentWriter(schema)
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
    segment = writer.build()
    store = JsonSegmentStore(segments_dir)
    store.save(segment)

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
    # Snippet should include highlighted text in either plain or HTML style
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
async def test_cache_warmup_reuses_segment(monkeypatch, tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SegmentWriter(schema)
    writer.add_document({"url": "https://example.com", "title": "Example", "body": "Example body"})
    store = JsonSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    load_calls = 0
    real_latest = JsonSegmentStore.latest

    def tracked_latest(self):
        nonlocal load_calls
        load_calls += 1
        return real_latest(self)

    monkeypatch.setattr(JsonSegmentStore, "latest", tracked_latest)

    await repository.warm_cache(docs_root)
    await repository.warm_cache(docs_root)

    assert load_calls == 1


@pytest.mark.asyncio
async def test_reload_cache_swaps_segment(tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SegmentWriter(schema)
    writer.add_document({"url": "https://example.com/old", "title": "Old", "body": "Old body"})
    store = JsonSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    await repository.warm_cache(docs_root)

    writer = SegmentWriter(schema)
    writer.add_document({"url": "https://example.com/new", "title": "New", "body": "New body"})
    store.save(writer.build())

    reloaded = await repository.reload_cache(docs_root)
    assert reloaded is True

    query = SearchQuery(
        original_text="new",
        normalized_tokens=["new"],
        extracted_keywords=KeywordSet(technical_terms=["new"]),
    )

    response = await repository.search_documents(query, docs_root)
    assert response.results
    assert response.results[0].document_url.endswith("/new")


@pytest.mark.asyncio
async def test_reload_cache_returns_false_when_missing_segments(tmp_path):
    docs_root = tmp_path / "tenant"
    docs_root.mkdir(parents=True)

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    result = await repository.reload_cache(docs_root)

    assert result is False


@pytest.mark.asyncio
async def test_ensure_resident_detects_manifest_changes(tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SegmentWriter(schema)
    writer.add_document({"url": "https://example.com/old", "title": "Old", "body": "Old body"})
    store = JsonSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    query = SearchQuery(
        original_text="new",
        normalized_tokens=["new"],
        extracted_keywords=KeywordSet(technical_terms=["new"]),
    )

    await repository.ensure_resident(docs_root, poll_interval=0.05)

    writer = SegmentWriter(schema)
    writer.add_document({"url": "https://example.com/new", "title": "New", "body": "New body"})
    store.save(writer.build())

    async def _wait_for_new_result() -> bool:
        for _ in range(40):
            response = await repository.search_documents(query, docs_root)
            if response.results and response.results[0].document_url.endswith("/new"):
                return True
            await asyncio.sleep(0.05)
        return False

    assert await _wait_for_new_result()
    await repository.stop_resident(docs_root)


@pytest.mark.asyncio
async def test_ensure_resident_respects_minimum_poll_interval(tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SegmentWriter(schema)
    writer.add_document({"url": "https://example.com/old", "title": "Old", "body": "Old body"})
    store = JsonSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
        min_manifest_poll_interval=0.05,
    )

    await repository.ensure_resident(docs_root, poll_interval=0.001)

    key = repository._cache_key(repository._segments_dir(docs_root))
    with repository._segments_lock:
        session = repository._resident_sessions[key]

    assert session.poll_interval == pytest.approx(0.05)
    await repository.stop_resident(docs_root)


@pytest.mark.asyncio
async def test_manifest_session_next_check_uses_minimum_interval(tmp_path, monkeypatch):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SegmentWriter(schema)
    writer.add_document({"url": "https://example.com/old", "title": "Old", "body": "Old body"})
    store = JsonSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
        min_manifest_poll_interval=0.05,
    )

    monkeypatch.setattr(repository, "_start_monitor_thread_locked", lambda: None)

    await repository.ensure_resident(docs_root, poll_interval=0.001)

    key = repository._cache_key(repository._segments_dir(docs_root))
    with repository._segments_lock:
        session = repository._resident_sessions[key]

    session.poll_interval = 0.001
    monkeypatch.setattr(indexed_repo_module.time, "monotonic", lambda: 500.0)

    repository._check_manifest_session(key, session)

    assert session.next_check_at == pytest.approx(500.0 + 0.05)
    await repository.stop_resident(docs_root)


@pytest.mark.asyncio
async def test_stop_resident_suspends_manifest_polling(tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SegmentWriter(schema)
    writer.add_document({"url": "https://example.com/old", "title": "Old", "body": "Old body"})
    store = JsonSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    query = SearchQuery(
        original_text="new",
        normalized_tokens=["new"],
        extracted_keywords=KeywordSet(technical_terms=["new"]),
    )

    await repository.ensure_resident(docs_root, poll_interval=0.05)
    await repository.stop_resident(docs_root)

    writer = SegmentWriter(schema)
    writer.add_document({"url": "https://example.com/new", "title": "New", "body": "New body"})
    store.save(writer.build())

    await asyncio.sleep(0.2)
    stalled_response = await repository.search_documents(query, docs_root)
    assert stalled_response.results == []

    await repository.ensure_resident(docs_root, poll_interval=0.05)

    async def _await_reload() -> bool:
        for _ in range(40):
            refreshed = await repository.search_documents(query, docs_root)
            if refreshed.results:
                return True
            await asyncio.sleep(0.05)
        return False

    assert await _await_reload()
    await repository.stop_resident(docs_root)
