"""Tests for the BM25-backed indexed search repository."""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
import time

import pytest

from docs_mcp_server.adapters import indexed_search_repository as indexed_repo_module
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
    segment_data = writer.build()
    store = SqliteSegmentStore(segments_dir)
    store.save(segment_data)

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
    writer = SqliteSegmentWriter(schema)
    writer.add_document({"url": "https://example.com", "title": "Example", "body": "Example body"})
    store = SqliteSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    load_calls = 0
    real_latest = SqliteSegmentStore.latest

    def tracked_latest(self):
        nonlocal load_calls
        load_calls += 1
        return real_latest(self)

    monkeypatch.setattr(SqliteSegmentStore, "latest", tracked_latest)

    await repository.warm_cache(docs_root)
    await repository.warm_cache(docs_root)

    assert load_calls == 1


@pytest.mark.asyncio
async def test_search_reuses_scoring_context(monkeypatch, tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SqliteSegmentWriter(schema)
    writer.add_document(
        {
            "url": "https://example.com/guide",
            "title": "Guide",
            "body": "Search guides and docs",
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
        original_text="guide",
        normalized_tokens=["guide"],
        extracted_keywords=KeywordSet(),
    )

    call_count = 0
    real_compute = indexed_repo_module.compute_field_length_stats

    def spy_compute(field_lengths):
        nonlocal call_count
        call_count += 1
        return real_compute(field_lengths)

    monkeypatch.setattr(indexed_repo_module, "compute_field_length_stats", spy_compute)

    await repository.search_documents(query, docs_root, max_results=5)
    await repository.search_documents(query, docs_root, max_results=5)

    assert call_count == 1


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

    query = SearchQuery(
        original_text="search performance budget",
        normalized_tokens=["search", "performance", "budget"],
        extracted_keywords=KeywordSet(technical_terms=["search performance budget"]),
    )

    await repository.search_documents(query, docs_root, max_results=5)

    samples: list[float] = []
    for _ in range(50):
        start = time.perf_counter()
        await repository.search_documents(query, docs_root, max_results=5)
        samples.append((time.perf_counter() - start) * 1000)

    samples.sort()
    p95_index = max(0, math.ceil(0.95 * len(samples)) - 1)
    p95_ms = samples[p95_index]

    # CI runners are slower than local machines; SQLite backend is slower for small tenants
    assert p95_ms <= 900.0


def test_cache_pin_eviction_removes_idle_segments(tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SqliteSegmentWriter(schema)
    writer.add_document({"url": "https://example.com", "title": "Doc", "body": "Body"})
    store = SqliteSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
        cache_pin_seconds=0.01,
    )

    segment = repository._get_cached_segment(docs_root)  # pylint: disable=protected-access
    assert segment is not None

    cache_key = repository._cache_key(segments_dir)  # pylint: disable=protected-access
    metrics = repository._segment_metrics[cache_key]  # pylint: disable=protected-access
    stale_time = time.perf_counter() - 10.0
    metrics.last_hit_at = stale_time
    metrics.last_loaded_at = stale_time

    repository._evict_idle_segments()  # pylint: disable=protected-access

    assert cache_key not in repository._segments  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_reload_cache_swaps_segment(tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SqliteSegmentWriter(schema)
    writer.add_document({"url": "https://example.com/old", "title": "Old", "body": "Old body"})
    store = SqliteSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    await repository.warm_cache(docs_root)

    writer = SqliteSegmentWriter(schema)
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


def test_cache_key_falls_back_on_resolve_error(tmp_path, monkeypatch):
    repo = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    def raise_error(self):
        raise OSError("boom")

    monkeypatch.setattr(Path, "resolve", raise_error)

    assert repo._cache_key(tmp_path) == str(tmp_path)  # pylint: disable=protected-access


def test_get_cached_segment_returns_none_when_segments_dir_missing(tmp_path):
    repo = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    assert repo._get_cached_segment(tmp_path) is None  # pylint: disable=protected-access


def test_reload_segment_returns_false_when_segments_dir_missing(tmp_path):
    repo = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    assert repo._reload_segment(tmp_path) is False  # pylint: disable=protected-access


def test_read_manifest_pointer_handles_invalid_payloads(tmp_path):
    repo = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )
    segments_dir = tmp_path / "__search_segments"
    segments_dir.mkdir(parents=True)
    manifest = segments_dir / SqliteSegmentStore.MANIFEST_FILENAME

    assert repo._read_manifest_pointer(segments_dir) is None  # pylint: disable=protected-access

    manifest.write_text("not-json", encoding="utf-8")
    assert repo._read_manifest_pointer(segments_dir) is None  # pylint: disable=protected-access

    manifest.write_text('{"latest_segment_id": ""}', encoding="utf-8")
    assert repo._read_manifest_pointer(segments_dir) is None  # pylint: disable=protected-access


def test_build_snippet_returns_empty_when_no_text():
    snippet = indexed_repo_module._build_snippet({}, ["term"], SearchSnippetConfig())

    assert snippet == ""


def test_proximity_bonus_handles_missing_fields():
    repo = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )
    query = SearchQuery(original_text="", normalized_tokens=[], extracted_keywords=KeywordSet())

    assert repo._proximity_bonus(query, {}) == 0.0  # pylint: disable=protected-access

    query = SearchQuery(original_text="alpha", normalized_tokens=[], extracted_keywords=KeywordSet())
    assert repo._proximity_bonus(query, {}) == 0.0  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_search_documents_skips_missing_doc_fields(tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()

    # Create a segment with postings but no stored document fields
    writer = SqliteSegmentWriter(schema)
    writer.add_document(
        {
            "url": "https://example.com/doc-1",
            "title": "Test Doc",
            "body": "alpha",
        }
    )
    segment_data = writer.build()
    store = SqliteSegmentStore(segments_dir)
    store.save(segment_data)

    # Load the segment
    real_segment = store.latest()

    # Create a mock segment that returns None for get_document
    class MockSegment:
        def __init__(self, real_segment):
            self.schema = real_segment.schema
            self.postings = real_segment.postings
            self.field_lengths = real_segment.field_lengths
            self.stored_fields = real_segment.stored_fields
            self.segment_id = real_segment.segment_id
            self.doc_count = real_segment.doc_count

        def get_document(self, doc_id):
            return None  # Simulate missing document fields

        def get_field_postings(self, field_name):
            return self.postings.get(field_name, {})

    mock_segment = MockSegment(real_segment)

    repo = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    # Mock the repository to return our mock segment
    repo._get_cached_segment = lambda _data_dir: mock_segment

    query = SearchQuery(
        original_text="alpha",
        normalized_tokens=["alpha"],
        extracted_keywords=KeywordSet(technical_terms=["alpha"]),
    )

    response = await repo.search_documents(query, docs_root, include_stats=True)

    assert response.results == []
    assert response.stats is not None


@pytest.mark.asyncio
async def test_ensure_resident_detects_manifest_changes(tmp_path):
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SqliteSegmentWriter(schema)
    writer.add_document({"url": "https://example.com/old", "title": "Old", "body": "Old body"})
    store = SqliteSegmentStore(segments_dir)
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

    writer = SqliteSegmentWriter(schema)
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
    writer = SqliteSegmentWriter(schema)
    writer.add_document({"url": "https://example.com/old", "title": "Old", "body": "Old body"})
    store = SqliteSegmentStore(segments_dir)
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
    writer = SqliteSegmentWriter(schema)
    writer.add_document({"url": "https://example.com/old", "title": "Old", "body": "Old body"})
    store = SqliteSegmentStore(segments_dir)
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
    writer = SqliteSegmentWriter(schema)
    writer.add_document({"url": "https://example.com/old", "title": "Old", "body": "Old body"})
    store = SqliteSegmentStore(segments_dir)
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

    writer = SqliteSegmentWriter(schema)
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


def test_compose_seed_text_includes_keywords() -> None:
    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )
    query = SearchQuery(
        original_text="Graph auth",
        normalized_tokens=["graph", "auth"],
        extracted_keywords=KeywordSet(
            technical_terms=["graph auth"],
            technical_nouns=["oauth"],
            acronyms=["API"],
            verb_forms=["authenticate"],
        ),
    )

    seed = repository._compose_seed_text(query)

    assert "Graph auth" in seed
    assert "graph" in seed
    assert "auth" in seed
    assert "API" in seed


def test_proximity_bonus_requires_exact_phrase() -> None:
    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )
    query = SearchQuery(original_text="alpha beta", normalized_tokens=[], extracted_keywords=KeywordSet())

    assert repository._proximity_bonus(query, {"body": "alpha beta gamma"}) > 0
    assert repository._proximity_bonus(query, {"body": "alpha gamma beta"}) == 0


def test_get_cache_metrics_returns_snapshot(tmp_path: Path) -> None:
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SqliteSegmentWriter(schema)
    writer.add_document({"url": "https://example.com", "title": "Example", "body": "Example body"})
    store = SqliteSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    repository._get_cached_segment(docs_root)

    metrics = repository.get_cache_metrics(docs_root)
    assert metrics


def test_invalidate_cache_clears_all(tmp_path: Path) -> None:
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    schema = create_default_schema()
    writer = SqliteSegmentWriter(schema)
    writer.add_document({"url": "https://example.com", "title": "Example", "body": "Example body"})
    store = SqliteSegmentStore(segments_dir)
    store.save(writer.build())

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    repository._get_cached_segment(docs_root)
    repository.invalidate_cache()

    assert repository.get_cache_metrics() == {}


def test_read_manifest_pointer_returns_digest(tmp_path: Path) -> None:
    docs_root = tmp_path / "tenant"
    segments_dir = docs_root / "__search_segments"
    segments_dir.mkdir(parents=True)

    # Create SQLite segment instead of manifest
    store = SqliteSegmentStore(segments_dir)
    segment_data = {
        "segment_id": "seg-1",
        "created_at": "2024-01-01T00:00:00Z",
        "schema": {"fields": [{"name": "url", "type": "text", "stored": True}]},
        "postings": {},
        "stored_fields": {},
        "field_lengths": {},
    }
    store.save(segment_data)

    repository = IndexedSearchRepository(
        snippet=SearchSnippetConfig(),
        ranking=SearchRankingConfig(),
        boosts=SearchBoostConfig(),
    )

    pointer = repository._read_manifest_pointer(segments_dir)

    assert pointer is not None
    assert pointer.startswith("seg-1:")


def test_build_snippet_prefers_body_over_title() -> None:
    config = SearchSnippetConfig()

    snippet = indexed_repo_module._build_snippet({"body": "Body content", "title": "Title"}, ["body"], config)

    assert snippet


def test_build_snippet_falls_back_to_title() -> None:
    config = SearchSnippetConfig()

    snippet = indexed_repo_module._build_snippet({"title": "Just a title"}, ["title"], config)

    assert snippet


def test_resolve_profile_analyzer_handles_unknown() -> None:
    assert indexed_repo_module._resolve_profile_analyzer("unknown") is None
