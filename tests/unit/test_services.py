"""Unit tests for Service Layer.

Following Cosmic Python Chapter 4: Service Layer Pattern
- Tests use case orchestration
- Tests transaction management via Unit of Work
- Uses FakeUnitOfWork for fast, isolated tests
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from docs_mcp_server.domain.model import Document
from docs_mcp_server.domain.search import (
    MatchTrace,
    SearchResponse,
    SearchResult,
    SearchStats as DomainSearchStats,
)
from docs_mcp_server.service_layer import services
from docs_mcp_server.service_layer.filesystem_unit_of_work import FakeUnitOfWork
from docs_mcp_server.utils.models import SearchStats


@pytest.fixture(autouse=True)
def clean_fake_uow():
    """Clear shared state before and after each test."""
    FakeUnitOfWork.clear_shared_store()
    yield
    FakeUnitOfWork.clear_shared_store()


@pytest.mark.unit
class TestGuardrailStats:
    """Cover guardrail stat synthesis helpers."""

    def test_build_guardrail_stats_matches_inputs(self):
        stats = services._build_guardrail_stats(warning="fallback", matches=3, error="boom")

        assert stats.warning == "fallback"
        assert stats.error == "boom"
        assert stats.matches == 3
        assert stats.files_found == 3
        assert stats.stage == 0
        assert stats.timed_out is False


@pytest.mark.unit
class TestFetchDocument:
    """Test fetch_document service function."""

    @pytest.mark.asyncio
    async def test_returns_document_if_exists(self):
        """Test fetching existing document."""
        # Setup: Store a document
        doc = Document.create(
            url="https://example.com/doc1", title="Test Doc", markdown="# Test", text="Test", excerpt=""
        )

        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        # Act: Fetch the document
        uow2 = FakeUnitOfWork()
        result = await services.fetch_document("https://example.com/doc1", uow2)

        # Assert
        assert result is not None
        assert result.url.value == "https://example.com/doc1"
        assert result.title == "Test Doc"

    @pytest.mark.asyncio
    async def test_returns_none_if_not_exists(self):
        """Test fetching non-existent document."""
        uow = FakeUnitOfWork()
        result = await services.fetch_document("https://example.com/missing", uow)

        assert result is None


@pytest.mark.unit
class TestStoreDocument:
    """Test store_document service function."""

    @pytest.mark.asyncio
    async def test_creates_new_document(self):
        """Test storing a new document."""
        uow = FakeUnitOfWork()
        result = await services.store_document(
            url="https://example.com/new",
            title="New Doc",
            markdown="# New",
            text="New content",
            excerpt="Excerpt",
            uow=uow,
        )

        # Verify document was created and stored
        assert result is not None
        assert result.url.value == "https://example.com/new"
        assert result.title == "New Doc"
        assert result.metadata.status == "success"

        # Verify it persisted
        uow2 = FakeUnitOfWork()
        async with uow2:
            saved = await uow2.documents.get("https://example.com/new")

        assert saved is not None
        assert saved.title == "New Doc"

    @pytest.mark.asyncio
    async def test_updates_existing_document(self):
        """Test updating an existing document."""
        # Setup: Create initial document
        doc = Document.create(
            url="https://example.com/existing", title="Old Title", markdown="# Old", text="Old content", excerpt=""
        )

        uow1 = FakeUnitOfWork()
        async with uow1:
            await uow1.documents.add(doc)
            await uow1.commit()

        # Act: Update the document
        uow2 = FakeUnitOfWork()
        result = await services.store_document(
            url="https://example.com/existing",
            title="New Title",
            markdown="# New",
            text="New content",
            excerpt="New excerpt",
            uow=uow2,
        )

        # Assert: Verify update
        assert result.title == "New Title"
        assert result.content.markdown == "# New"
        assert result.content.text == "New content"
        assert result.metadata.status == "success"

    @pytest.mark.asyncio
    async def test_marks_document_as_success(self):
        """Test that storing marks document as successfully fetched."""
        uow = FakeUnitOfWork()
        result = await services.store_document(
            url="https://example.com/doc", title="Doc", markdown="# Doc", text="Doc", excerpt="", uow=uow
        )

        assert result.metadata.status == "success"
        assert result.metadata.last_fetched_at is not None
        assert result.metadata.retry_count == 0

    @pytest.mark.asyncio
    async def test_missing_excerpt_defaults_to_empty_string(self):
        """Store guardrail: excerpt None should degrade gracefully for downstream tools."""
        uow = FakeUnitOfWork()
        stored = await services.store_document(
            url="https://example.com/guardrail",
            title="Guardrail",
            markdown="# Content",
            text="Content",
            excerpt=None,
            uow=uow,
        )

        assert stored.content.excerpt == ""
        # Ensure the persisted copy also keeps the normalized excerpt
        persisted = await services.fetch_document("https://example.com/guardrail", FakeUnitOfWork())
        assert persisted is not None
        assert persisted.content.excerpt == ""


@pytest.mark.unit
class TestMarkDocumentFailed:
    """Test mark_document_failed service function."""

    @pytest.mark.asyncio
    async def test_increments_retry_count(self):
        """Test marking document as failed increments retry count."""
        # Setup: Create document
        doc = Document.create(url="https://example.com/doc", title="Doc", markdown="# Doc", text="Doc", excerpt="")

        uow1 = FakeUnitOfWork()
        async with uow1:
            await uow1.documents.add(doc)
            await uow1.commit()

        # Act: Mark as failed
        uow2 = FakeUnitOfWork()
        await services.mark_document_failed("https://example.com/doc", uow2)

        # Assert: Verify retry count increased
        uow3 = FakeUnitOfWork()
        async with uow3:
            updated = await uow3.documents.get("https://example.com/doc")

        assert updated is not None
        assert updated.metadata.retry_count == 1
        assert updated.metadata.status == "failed"

    @pytest.mark.asyncio
    async def test_handles_missing_document(self):
        """Test marking non-existent document as failed doesn't error."""
        uow = FakeUnitOfWork()
        # Should not raise exception
        await services.mark_document_failed("https://example.com/missing", uow)


@pytest.mark.unit
class TestSearchDocuments:
    """Test search_documents service function."""

    @pytest.mark.asyncio
    async def test_finds_matching_documents(self):
        """Test searching finds documents by title/content."""
        # Setup: Create test documents
        doc1 = Document.create(
            url="https://example.com/python",
            title="Python Guide",
            markdown="# Python",
            text="Python programming",
            excerpt="",
        )
        doc2 = Document.create(
            url="https://example.com/java", title="Java Guide", markdown="# Java", text="Java programming", excerpt=""
        )

        uow1 = FakeUnitOfWork()
        async with uow1:
            await uow1.documents.add(doc1)
            await uow1.documents.add(doc2)
            await uow1.commit()

        # Mock search service that returns SearchResult objects
        mock_search_service = AsyncMock()
        search_result = SearchResult(
            document_url="file:///path/to/python.md",
            document_title="Python Guide",
            snippet="Python programming...",
            match_trace=MatchTrace(
                stage=1,
                stage_name="exact_phrase",
                query_variant="python",
                match_reason="Exact phrase match",
                ripgrep_flags=["--fixed-strings"],
            ),
            relevance_score=0.95,
        )
        mock_search_service.search = AsyncMock(return_value=SearchResponse(results=[search_result], stats=None))

        # Act: Search for "python"
        uow2 = FakeUnitOfWork()
        results, stats = await services.search_documents_filesystem(
            query="python",
            search_service=mock_search_service,
            uow=uow2,
            data_dir=Path("/tmp/test_data"),
            limit=10,
        )

        # Assert: Result converted to transient document since not in repo
        assert len(results) == 1
        assert results[0].title == "Python Guide"
        assert isinstance(results[0], Document)
        # Stats are None with new search (trace metadata is in SearchResult instead)
        assert stats is None

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_matches(self):
        """Test searching returns empty list when no matches."""
        mock_search_service = AsyncMock()
        mock_search_service.search = AsyncMock(return_value=SearchResponse(results=[], stats=None))

        uow = FakeUnitOfWork()
        results, stats = await services.search_documents_filesystem(
            query="nonexistent",
            search_service=mock_search_service,
            uow=uow,
            data_dir=Path("/tmp/test_data"),
            limit=10,
        )

        assert results == []
        assert stats is None

    @pytest.mark.asyncio
    async def test_respects_limit(self):
        """Test search respects limit parameter."""
        # Setup: Create multiple documents
        uow1 = FakeUnitOfWork()
        async with uow1:
            for i in range(5):
                doc = Document.create(
                    url=f"https://example.com/test{i}",
                    title=f"Test Doc {i}",
                    markdown=f"# Test {i}",
                    text="test content",
                    excerpt="",
                )
                await uow1.documents.add(doc)
            await uow1.commit()

        # Mock search service returning 3 SearchResult objects
        mock_search_service = AsyncMock()
        search_results = [
            SearchResult(
                document_url=f"file:///path/to/test{i}.md",
                document_title=f"Test Doc {i}",
                snippet="test content...",
                match_trace=MatchTrace(
                    stage=1,
                    stage_name="exact_phrase",
                    query_variant="test",
                    match_reason="Match",
                    ripgrep_flags=["--fixed-strings"],
                ),
                relevance_score=0.8,
            )
            for i in range(3)
        ]
        mock_search_service.search = AsyncMock(return_value=SearchResponse(results=search_results, stats=None))

        # Act: Search with limit=3
        uow2 = FakeUnitOfWork()
        results, stats = await services.search_documents_filesystem(
            query="test",
            search_service=mock_search_service,
            uow=uow2,
            data_dir=Path("/tmp/test_data"),
            limit=3,
        )

        # Assert: Returns at most 3 results
        assert len(results) <= 3
        assert stats is None

    @pytest.mark.asyncio
    async def test_existing_document_updated_with_search_metadata(self):
        """Context assembly guardrail: persisted docs inherit telemetry before returning."""
        existing = Document.create(
            url="file:///tmp/docs/python.md",
            title="Python",
            markdown="# python",
            text="python",
            excerpt="",
        )
        uow_seed = FakeUnitOfWork()
        async with uow_seed:
            await uow_seed.documents.add(existing)
            await uow_seed.commit()

        search_result = SearchResult(
            document_url="file:///tmp/docs/python.md#L10",
            document_title="Python",
            snippet="match",
            match_trace=MatchTrace(
                stage=2,
                stage_name="and_query",
                query_variant="python",
                match_reason="Existing",
                ripgrep_flags=["-w"],
            ),
            relevance_score=0.88,
        )
        mock_search_service = AsyncMock()
        mock_search_service.search = AsyncMock(return_value=SearchResponse(results=[search_result], stats=None))

        uow = FakeUnitOfWork()
        results, _ = await services.search_documents_filesystem(
            query="python",
            search_service=mock_search_service,
            uow=uow,
            data_dir=Path("/tmp/docs"),
            limit=5,
        )

        assert len(results) == 1
        doc = results[0]
        assert doc.score == pytest.approx(0.88)
        assert doc.snippet == "match"
        assert doc.match_stage == 2
        assert doc.match_stage_name == "and_query"
        assert doc.match_query_variant == "python"
        assert doc.match_reason == "Existing"
        assert doc.match_ripgrep_flags == ["-w"]

    @pytest.mark.asyncio
    async def test_word_match_and_stats_flags_forwarded(self):
        """Router guardrail: ensure SearchService sees the exact knobs requested by the caller."""
        domain_stats = DomainSearchStats(
            stage=4,
            files_found=2,
            matches_found=1,
            files_searched=7,
            search_time=0.42,
            warning="slow",
        )
        search_result = SearchResult(
            document_url="file:///tmp/docs/guardrail.md",
            document_title="Guardrail",
            snippet="snippet",
            match_trace=MatchTrace(
                stage=4,
                stage_name="fallback",
                query_variant="guardrail",
                match_reason="Fallback",
                ripgrep_flags=["--pcre2"],
            ),
            relevance_score=0.51,
        )
        mock_search_service = AsyncMock()
        mock_search_service.search = AsyncMock(return_value=SearchResponse(results=[search_result], stats=domain_stats))

        data_dir = Path("/tmp/docs")
        results, stats = await services.search_documents_filesystem(
            query="guardrail",
            search_service=mock_search_service,
            uow=FakeUnitOfWork(),
            data_dir=data_dir,
            limit=5,
            word_match=True,
            include_stats=True,
        )

        mock_search_service.search.assert_awaited_once_with(
            raw_query="guardrail",
            data_dir=data_dir,
            max_results=5,
            word_match=True,
            include_stats=True,
            tenant_context=None,
        )
        assert len(results) == 1
        assert stats is not None
        assert stats.warning == "slow"

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_list(self):
        """Test empty query returns empty list."""
        mock_search_service = AsyncMock()

        uow = FakeUnitOfWork()
        results, stats = await services.search_documents_filesystem(
            query="",
            search_service=mock_search_service,
            uow=uow,
            data_dir=Path("/tmp/test_data"),
            limit=10,
        )

        assert results == []
        assert stats is None  # Empty query returns None stats
        # Search service should not be called for empty queries
        mock_search_service.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_documents_converts_domain_stats(self):
        """Domain SearchStats should be converted to utils SearchStats."""
        domain_stats = DomainSearchStats(
            stage=3,
            files_found=5,
            matches_found=3,
            files_searched=10,
            search_time=0.25,
            warning=None,
        )
        search_result = SearchResult(
            document_url="file:///missing.md",
            document_title="Missing",
            snippet="missing lines",
            match_trace=MatchTrace(
                stage=3,
                stage_name="relaxed_match",
                query_variant="missing",
                match_reason="Relaxed",
                ripgrep_flags=["--ignore-case"],
            ),
            relevance_score=0.4,
        )
        mock_search_service = AsyncMock()
        mock_search_service.search = AsyncMock(return_value=SearchResponse(results=[search_result], stats=domain_stats))

        uow = FakeUnitOfWork()
        results, stats = await services.search_documents_filesystem(
            query="missing content",
            search_service=mock_search_service,
            uow=uow,
            data_dir=Path("/tmp/test_data"),
            limit=2,
            include_stats=True,
        )

        assert len(results) == 1
        assert stats is not None
        assert stats.stage == 3
        assert stats.files_found == 5

    @pytest.mark.asyncio
    async def test_search_documents_handles_service_errors_with_guardrails(self):
        """Search router should fall back to guardrail stats when the search backend fails."""
        mock_search_service = AsyncMock()
        mock_search_service.search = AsyncMock(side_effect=RuntimeError("boom"))

        results, stats = await services.search_documents_filesystem(
            query="boom",
            search_service=mock_search_service,
            uow=FakeUnitOfWork(),
            data_dir=Path("/tmp/data"),
            limit=5,
            include_stats=True,
        )

        assert results == []
        assert stats is not None
        assert stats.error == "boom"
        assert "error" in (stats.warning or "").lower()

    @pytest.mark.asyncio
    async def test_search_documents_service_error_without_stats_flag(self):
        """Guardrail stats still include salient warnings when include_stats=False."""
        mock_search_service = AsyncMock()
        mock_search_service.search = AsyncMock(side_effect=RuntimeError("boom"))

        results, stats = await services.search_documents_filesystem(
            query="boom",
            search_service=mock_search_service,
            uow=FakeUnitOfWork(),
            data_dir=Path("/tmp/data"),
            limit=5,
        )

        assert results == []
        assert stats is not None
        assert isinstance(stats, SearchStats)
        assert stats.matches == 0
        assert stats.files_found == 0
        assert "search service error" in (stats.warning or "").lower()
        assert stats.error == "boom"

    @pytest.mark.asyncio
    async def test_search_documents_synthesizes_stats_when_missing(self):
        """Telemetry fallback should synthesize stats when include_stats=True but backend omits them."""
        transient_result = SearchResult(
            document_url="file:///tmp/fallback.md",
            document_title="Fallback",
            snippet="context",
            match_trace=MatchTrace(
                stage=3,
                stage_name="fallback",
                query_variant="fallback",
                match_reason="Transient",
                ripgrep_flags=["--fixed-strings"],
            ),
            relevance_score=0.4,
        )
        mock_search_service = AsyncMock()
        mock_search_service.search = AsyncMock(return_value=SearchResponse(results=[transient_result], stats=None))

        results, stats = await services.search_documents_filesystem(
            query="fallback",
            search_service=mock_search_service,
            uow=FakeUnitOfWork(),
            data_dir=Path("/tmp/data"),
            limit=5,
            include_stats=True,
        )

        assert len(results) == 1
        assert stats is not None
        assert stats.matches == 1
        assert "synthesized" in (stats.warning or "").lower()

    @pytest.mark.asyncio
    async def test_search_documents_clamps_requested_limit(self):
        """Ensure routing layer enforces the max-results guardrail before invoking SearchService."""
        mock_search_service = AsyncMock()
        mock_search_service.search = AsyncMock(return_value=SearchResponse(results=[], stats=None))

        await services.search_documents_filesystem(
            query="python",
            search_service=mock_search_service,
            uow=FakeUnitOfWork(),
            data_dir=Path("/tmp/data"),
            limit=999,
        )

        awaited_kwargs = mock_search_service.search.await_args.kwargs
        assert awaited_kwargs["max_results"] == services.MAX_SEARCH_RESULTS

    @pytest.mark.asyncio
    async def test_search_documents_clamps_floor(self):
        """Zero or negative limits should still request at least one result."""
        mock_search_service = AsyncMock()
        mock_search_service.search = AsyncMock(return_value=SearchResponse(results=[], stats=None))

        await services.search_documents_filesystem(
            query="python",
            search_service=mock_search_service,
            uow=FakeUnitOfWork(),
            data_dir=Path("/tmp/data"),
            limit=0,
        )

        awaited_kwargs = mock_search_service.search.await_args.kwargs
        assert awaited_kwargs["max_results"] == 1

    @pytest.mark.asyncio
    async def test_search_documents_mixed_repository_and_transient_docs(self):
        """Router should enrich repo hits and fabricate transient docs in one response."""
        managed = Document.create(
            url="file:///tmp/docs/managed.md",
            title="Managed",
            markdown="# Managed",
            text="managed",
            excerpt="",
        )
        seed = FakeUnitOfWork()
        async with seed:
            await seed.documents.add(managed)
            await seed.commit()

        existing_result = SearchResult(
            document_url=f"{managed.url.value}#L10",
            document_title="Managed",
            snippet="existing context",
            match_trace=MatchTrace(
                stage=2,
                stage_name="exact",
                query_variant="managed",
                match_reason="persisted",
                ripgrep_flags=["--fixed-strings"],
            ),
            relevance_score=0.9,
        )
        transient_result = SearchResult(
            document_url="file:///tmp/docs/transient.md",
            document_title="Transient",
            snippet="transient context",
            match_trace=MatchTrace(
                stage=3,
                stage_name="fallback",
                query_variant="transient",
                match_reason="new",
                ripgrep_flags=["--ignore-case"],
            ),
            relevance_score=0.4,
        )
        mock_search_service = AsyncMock()
        domain_stats = DomainSearchStats(
            stage=3,
            files_found=2,
            matches_found=2,
            files_searched=5,
            search_time=0.33,
            warning="bench",
        )
        mock_search_service.search = AsyncMock(
            return_value=SearchResponse(results=[existing_result, transient_result], stats=domain_stats)
        )

        results, stats = await services.search_documents_filesystem(
            query="managed transient",
            search_service=mock_search_service,
            uow=FakeUnitOfWork(),
            data_dir=Path("/tmp/docs"),
            limit=5,
            include_stats=True,
        )

        assert len(results) == 2
        managed_doc = results[0]
        transient_doc = results[1]
        # URL now includes fragment from search result (preserves line number)
        assert managed_doc.url.value == f"{managed.url.value}#L10"
        assert managed_doc.snippet == "existing context"
        assert managed_doc.match_reason == "persisted"
        assert transient_doc.url.value == "file:///tmp/docs/transient.md"
        assert transient_doc.snippet == "transient context"
        assert transient_doc.match_stage_name == "fallback"
        assert stats is not None
        assert stats.files_found == 2

    @pytest.mark.asyncio
    async def test_whitespace_only_query_returns_empty(self):
        """Whitespace-only queries should short-circuit before hitting the search backend."""
        mock_search_service = AsyncMock()

        results, stats = await services.search_documents_filesystem(
            query="   ",
            search_service=mock_search_service,
            uow=FakeUnitOfWork(),
            data_dir=Path("/tmp/data"),
            limit=5,
        )

        assert results == []
        assert stats is None
        mock_search_service.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_documents_logs_errors(self, caplog):
        """The guardrail path should emit exception logs for observability."""
        mock_search_service = AsyncMock()
        mock_search_service.search = AsyncMock(side_effect=RuntimeError("boom"))

        caplog.set_level("ERROR")
        await services.search_documents_filesystem(
            query="boom",
            search_service=mock_search_service,
            uow=FakeUnitOfWork(),
            data_dir=Path("/tmp/data"),
            limit=5,
        )

        assert "Search service failed for query" in caplog.text
