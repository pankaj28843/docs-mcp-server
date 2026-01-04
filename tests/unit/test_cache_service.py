"""Unit tests for CacheService.

Following Cosmic Python principles:
- Tests use FakeUnitOfWork for fast, isolated tests
- Tests don't require external dependencies (ES, Readability)
- Tests verify service orchestration and caching logic
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.domain.model import Document
from docs_mcp_server.service_layer.filesystem_unit_of_work import FakeUnitOfWork
from docs_mcp_server.services.cache_service import CacheService
from docs_mcp_server.utils.doc_fetcher import DocFetchError
from docs_mcp_server.utils.models import DocPage, ReadabilityContent


@pytest.fixture(autouse=True)
def clean_fake_uow():
    """Clear shared state before and after each test."""
    FakeUnitOfWork.clear_shared_store()
    yield
    FakeUnitOfWork.clear_shared_store()


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    settings = Settings(
        docs_name="Test Docs",
        docs_sitemap_url="https://example.com/sitemap.xml",
        url_whitelist_prefixes="https://example.com/",
        min_fetch_interval_hours=24.0,
    )
    settings.semantic_cache_enabled = False
    return settings


@pytest.fixture
def uow_factory():
    """Factory for creating FakeUnitOfWork instances."""
    return lambda: FakeUnitOfWork()


@pytest.fixture
def cache_service(mock_settings, uow_factory):
    """Create CacheService instance for testing."""
    return CacheService(settings=mock_settings, uow_factory=uow_factory)


@pytest.mark.unit
class TestCacheServiceInitialization:
    """Test CacheService initialization."""

    def test_creates_service_with_settings(self, cache_service):
        """Test service can be created with settings."""
        assert cache_service is not None
        assert cache_service.min_fetch_interval_hours == 24.0

    def test_offline_mode_detection(self, mock_settings, uow_factory):
        """Test offline mode is properly detected from settings."""
        # Use is_offline_mode() method instead of offline_mode attribute
        service = CacheService(settings=mock_settings, uow_factory=uow_factory)
        # By default, is_offline_mode() returns False
        assert service.offline_mode is False

    @pytest.mark.asyncio
    async def test_ensure_ready_initializes_fetcher(self, cache_service):
        """Test ensure_ready initializes the fetcher."""
        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher_class.return_value = mock_fetcher

            await cache_service.ensure_ready()

            assert cache_service._fetcher is not None
            mock_fetcher.__aenter__.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_cleans_up_resources(self, cache_service):
        """Test close properly cleans up resources."""
        # Initialize fetcher first
        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher_class.return_value = mock_fetcher

            await cache_service.ensure_ready()
            await cache_service.close()

            assert cache_service._fetcher is None
            mock_fetcher.__aexit__.assert_called_once()


@pytest.mark.unit
class TestCacheHitMiss:
    """Test cache hit/miss logic."""

    @pytest.mark.asyncio
    async def test_cache_hit_for_fresh_document(self, cache_service):
        """Test cache returns document if fresh (within TTL)."""
        # Setup: Store a fresh document
        doc = Document.create(
            url="https://example.com/doc",
            title="Test Doc",
            markdown="# Test",
            text="Test content",
            excerpt="Test excerpt",
        )
        doc.metadata.last_fetched_at = datetime.now(timezone.utc)
        doc.metadata.mark_success()

        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        # Act: Try to get cached document
        result = await cache_service.get_cached_document("https://example.com/doc")

        # Assert: Should return cached document
        assert result is not None
        assert result.url == "https://example.com/doc"
        assert result.title == "Test Doc"

    @pytest.mark.asyncio
    async def test_cache_miss_for_stale_document(self, cache_service):
        """Test cache returns None for stale document (beyond TTL)."""
        # Setup: Store a stale document (48 hours old)
        doc = Document.create(
            url="https://example.com/old", title="Old Doc", markdown="# Old", text="Old content", excerpt=""
        )
        doc.metadata.last_fetched_at = datetime.now(timezone.utc) - timedelta(hours=48)

        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        # Act: Try to get cached document
        result = await cache_service.get_cached_document("https://example.com/old")

        # Assert: Should return None (stale)
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_miss_for_nonexistent_document(self, cache_service):
        """Test cache returns None for document not in cache."""
        result = await cache_service.get_cached_document("https://example.com/missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_requires_last_fetched_timestamp(self, cache_service):
        """Guardrail: cache miss if metadata lacks last_fetched_at."""
        doc = Document.create(
            url="https://example.com/no-timestamp",
            title="Timestampless",
            markdown="# Doc",
            text="content",
            excerpt="",
        )

        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        result = await cache_service.get_cached_document("https://example.com/no-timestamp")

        assert result is None

    @pytest.mark.asyncio
    async def test_stale_cache_returns_old_document_in_offline_mode(self, uow_factory, tmp_path):
        """Test stale cache can be retrieved in offline mode."""
        # Create settings with offline mode enabled
        # Use DOCS_ENTRY_URL without sitemap to trigger offline mode detection
        mock_settings = Settings(
            docs_name="Test Docs",
            docs_entry_url="https://example.com/",
            url_whitelist_prefixes="https://example.com/",
            min_fetch_interval_hours=24.0,
        )
        service = CacheService(settings=mock_settings, uow_factory=uow_factory)

        # Setup: Store stale document
        doc = Document.create(
            url="https://example.com/stale", title="Stale Doc", markdown="# Stale", text="Stale content", excerpt=""
        )
        doc.metadata.last_fetched_at = datetime.now(timezone.utc) - timedelta(hours=72)

        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        # Act: Get stale cached document
        result = await service.get_stale_cached_document("https://example.com/stale")

        # Assert: Should return even if stale
        assert result is not None
        assert result.url == "https://example.com/stale"


@pytest.mark.unit
class TestFetchAndCache:
    """Test fetching and caching documents."""

    @pytest.mark.asyncio
    async def test_fetch_and_cache_success(self, cache_service):
        """Test successful fetch and cache of document."""
        # Mock fetcher
        mock_page = DocPage(
            url="https://example.com/new",
            title="New Doc",
            content="New content",
            readability_content=ReadabilityContent(
                raw_html="<html>Raw</html>",
                extracted_content="Extracted content",
                processed_markdown="# Processed",
                excerpt="Excerpt",
                title="New Doc",
                byline=None,
                length=100,
                lang="en",
                success=True,
                extraction_method="readability",
            ),
        )

        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_page = AsyncMock(return_value=mock_page)
            mock_fetcher_class.return_value = mock_fetcher

            await cache_service.ensure_ready()

            # Fetch and cache
            page, failure_reason = await cache_service.fetch_and_cache("https://example.com/new")

            # Assert: Returns page
            assert page is not None
            assert page.url == "https://example.com/new"
            assert failure_reason is None

            # Verify document was cached
            uow = FakeUnitOfWork()
            async with uow:
                cached_doc = await uow.documents.get("https://example.com/new")

            assert cached_doc is not None
            assert cached_doc.title == "New Doc"
            assert cached_doc.metadata.status == "success"

    @pytest.mark.asyncio
    async def test_fetch_and_cache_failure(self, cache_service):
        """Test fetch failure marks document as failed."""
        # Mock fetcher to return None (failure)
        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_page = AsyncMock(return_value=None)
            mock_fetcher_class.return_value = mock_fetcher

            await cache_service.ensure_ready()

            # Act: Try to fetch
            page, failure_reason = await cache_service.fetch_and_cache("https://example.com/fail")

            # Assert: Returns None and reason provided
            assert page is None
            assert isinstance(failure_reason, str)

    @pytest.mark.asyncio
    async def test_fetch_and_cache_exception_handling(self, cache_service):
        """Test exception during fetch is handled gracefully."""
        # Mock fetcher to raise exception
        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_page = AsyncMock(side_effect=Exception("Network error"))
            mock_fetcher_class.return_value = mock_fetcher

            await cache_service.ensure_ready()

            # Act: Try to fetch (should not raise)
            page, failure_reason = await cache_service.fetch_and_cache("https://example.com/error")

            # Assert: Returns None with reason
            assert page is None
            assert failure_reason.startswith("unexpected_error")

    @pytest.mark.asyncio
    async def test_fetch_and_cache_mercury_fallback_without_readability(self, cache_service):
        """Playwright/mercury fallback should still cache documents when Readability data is missing."""
        fallback_page = DocPage(
            url="https://example.com/fallback",
            title="Fallback Doc",
            content="Fallback markdown body",
            extraction_method="playwright_cascade",
            readability_content=None,  # Simulates cascading extractor success without Readability
        )

        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_page = AsyncMock(return_value=fallback_page)
            mock_fetcher_class.return_value = mock_fetcher

            await cache_service.ensure_ready()
            page, failure_reason = await cache_service.fetch_and_cache(fallback_page.url)

        assert page is fallback_page
        assert failure_reason is None

        verifier = FakeUnitOfWork()
        async with verifier:
            stored = await verifier.documents.get(fallback_page.url)

        assert stored is not None
        assert stored.title == "Fallback Doc"
        assert stored.content.text == "Fallback markdown body"

    @pytest.mark.asyncio
    async def test_fetch_and_cache_initializes_fetcher_on_demand(self, cache_service):
        """Coverage guardrail: fetch_and_cache should lazy-init fetcher when needed."""
        lazy_page = DocPage(
            url="https://example.com/lazy",
            title="Lazy Init",
            content="Body",
            readability_content=None,
        )

        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.__aenter__ = AsyncMock(return_value=mock_fetcher)
            mock_fetcher.fetch_page = AsyncMock(return_value=lazy_page)
            mock_fetcher_class.return_value = mock_fetcher

            page, failure_reason = await cache_service.fetch_and_cache(lazy_page.url)

        assert page is lazy_page
        assert failure_reason is None
        mock_fetcher_class.assert_called_once()
        mock_fetcher.__aenter__.assert_awaited_once()
        mock_fetcher.fetch_page.assert_awaited_once_with(lazy_page.url)

    @pytest.mark.asyncio
    async def test_fetch_and_cache_surfaces_fetch_error_reason(self, cache_service):
        """DocFetchError reasons should be bubbled up for telemetry."""
        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_page = AsyncMock(side_effect=DocFetchError("fallback_extractor_failed", "status=500"))
            mock_fetcher_class.return_value = mock_fetcher

            await cache_service.ensure_ready()
            page, failure_reason = await cache_service.fetch_and_cache("https://example.com/missing")

        assert page is None
        assert failure_reason.startswith("fallback_extractor_failed")

    @pytest.mark.asyncio
    async def test_fetch_and_cache_reports_cache_write_failure(self, cache_service):
        """Cache write failures should bubble up as fetch failures."""

        failing_page = DocPage(
            url="https://example.com/store-error",
            title="Broken",
            content="body",
            readability_content=None,
        )

        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_page = AsyncMock(return_value=failing_page)
            mock_fetcher_class.return_value = mock_fetcher

            await cache_service.ensure_ready()
            cache_service._cache_document = AsyncMock(return_value=(False, "cache_store_failed:ValidationError"))
            cache_service._mark_document_failure = AsyncMock()

            page, failure_reason = await cache_service.fetch_and_cache(failing_page.url)

        assert page is None
        assert failure_reason == "cache_store_failed:ValidationError"
        cache_service._mark_document_failure.assert_awaited_once_with(failing_page.url)


@pytest.mark.unit
class TestCheckAndFetchPage:
    """Test the primary check_and_fetch_page method."""

    @pytest.mark.asyncio
    async def test_returns_cached_if_fresh(self, cache_service):
        """Test returns cached document if fresh."""
        # Setup: Store fresh document
        doc = Document.create(
            url="https://example.com/doc", title="Cached Doc", markdown="# Cached", text="Cached content", excerpt=""
        )
        doc.metadata.last_fetched_at = datetime.now(timezone.utc)
        doc.metadata.mark_success()

        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher"):
            await cache_service.ensure_ready()

            # Act
            page, is_cache_hit, failure_reason = await cache_service.check_and_fetch_page("https://example.com/doc")

            # Assert
            assert page is not None
            assert is_cache_hit is True
            assert page.title == "Cached Doc"
            assert failure_reason is None

    @pytest.mark.asyncio
    async def test_fetches_if_not_cached(self, cache_service):
        """Test fetches from source if not in cache."""
        mock_page = DocPage(
            url="https://example.com/fetch",
            title="Fetched Doc",
            content="Fetched content",
            readability_content=ReadabilityContent(
                raw_html="<html>Raw</html>",
                extracted_content="Extracted",
                processed_markdown="# Fetched",
                excerpt="",
                title="Fetched Doc",
                byline=None,
                length=100,
                lang="en",
                success=True,
                extraction_method="readability",
            ),
        )

        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_page = AsyncMock(return_value=mock_page)
            mock_fetcher_class.return_value = mock_fetcher

            await cache_service.ensure_ready()

            # Act
            page, is_cache_hit, failure_reason = await cache_service.check_and_fetch_page("https://example.com/fetch")

            # Assert
            assert page is not None
            assert is_cache_hit is False
            assert page.title == "Fetched Doc"
            assert failure_reason is None

    @pytest.mark.asyncio
    async def test_offline_mode_returns_stale_cache(self, uow_factory):
        """Test stale cache behavior when in offline mode."""
        # For this test, we just verify get_stale_cached_document works
        # Actual offline mode detection is tested in integration tests
        mock_settings = Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
            url_whitelist_prefixes="https://example.com/",
            min_fetch_interval_hours=24.0,
        )
        service = CacheService(settings=mock_settings, uow_factory=uow_factory)

        # Setup: Store stale document
        doc = Document.create(
            url="https://example.com/offline",
            title="Offline Doc",
            markdown="# Offline",
            text="Offline content",
            excerpt="",
        )
        doc.metadata.last_fetched_at = datetime.now(timezone.utc) - timedelta(hours=72)

        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        # Act: Get stale cached document (simulating offline mode behavior)
        page = await service.get_stale_cached_document("https://example.com/offline")

        # Assert: Returns stale cache
        assert page is not None
        assert page.url == "https://example.com/offline"

    @pytest.mark.asyncio
    async def test_offline_mode_without_cache_skips_network_fetch(self, mock_settings, uow_factory):
        """Offline guardrail: avoid new fetches when cache miss occurs."""
        service = CacheService(settings=mock_settings, uow_factory=uow_factory)
        service.offline_mode = True  # Force offline guardrail

        service.ensure_ready = AsyncMock()
        service.get_cached_document = AsyncMock(return_value=None)
        service.get_stale_cached_document = AsyncMock(return_value=None)
        service.fetch_and_cache = AsyncMock()
        service._get_semantic_cache_hits = AsyncMock(return_value=([], False))

        page, is_cache_hit, failure_reason = await service.check_and_fetch_page("https://example.com/offline-guardrail")

        assert page is None
        assert is_cache_hit is False
        assert failure_reason == "offline_no_cache"
        service.fetch_and_cache.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_semantic_cache_hit_short_circuits_fetch(self, mock_settings, uow_factory):
        mock_settings.semantic_cache_enabled = True

        def embed(text: str) -> list[float]:
            return [1.0, 0.0] if "install" in text or "setup" in text else [0.0, 1.0]

        service = CacheService(settings=mock_settings, uow_factory=uow_factory, embedding_provider=embed)
        service.ensure_ready = AsyncMock()
        service.fetch_and_cache = AsyncMock()

        doc = Document.create(
            url="https://example.com/setup-guide",
            title="Setup Guide",
            markdown="# Setup",
            text="Install steps",
            excerpt="",
        )
        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        page, is_cache_hit, failure_reason = await service.check_and_fetch_page("https://example.com/install")

        assert is_cache_hit is True
        assert page is not None
        assert page.title == "Setup Guide"
        assert failure_reason is None
        service.fetch_and_cache.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_semantic_cache_false_positive_triggers_fetch(self, mock_settings, uow_factory, caplog):
        mock_settings.semantic_cache_enabled = True
        mock_settings.semantic_cache_similarity_threshold = 0.95

        def embed(text: str) -> list[float]:
            return [1.0, 0.0] if "install" in text else [0.0, 1.0]

        service = CacheService(settings=mock_settings, uow_factory=uow_factory, embedding_provider=embed)
        service.ensure_ready = AsyncMock()
        fetched_page = DocPage(
            url="https://example.com/install",
            title="Install",
            content="body",
            readability_content=None,
        )
        service.fetch_and_cache = AsyncMock(return_value=(fetched_page, None))

        doc = Document.create(
            url="https://example.com/reference",
            title="API Reference",
            markdown="# Ref",
            text="Reference",
            excerpt="",
        )
        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        with caplog.at_level("INFO"):
            page, is_cache_hit, failure_reason = await service.check_and_fetch_page("https://example.com/install")

        assert page is fetched_page
        assert is_cache_hit is False
        assert failure_reason is None
        assert "Semantic cache candidate rejected" in caplog.text
        service.fetch_and_cache.assert_awaited_once_with("https://example.com/install")

    @pytest.mark.asyncio
    async def test_semantic_cache_can_be_disabled_per_call(self, mock_settings, uow_factory):
        mock_settings.semantic_cache_enabled = True

        def embed(text: str) -> list[float]:
            return [1.0, 0.0] if "setup" in text else [0.0, 1.0]

        service = CacheService(settings=mock_settings, uow_factory=uow_factory, embedding_provider=embed)
        service.ensure_ready = AsyncMock()
        fetched_page = DocPage(
            url="https://example.com/install",
            title="Install",
            content="body",
            readability_content=None,
        )
        service.fetch_and_cache = AsyncMock(return_value=(fetched_page, None))

        doc = Document.create(
            url="https://example.com/setup-guide",
            title="Setup Guide",
            markdown="# Setup",
            text="Install steps",
            excerpt="",
        )
        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

            page, is_cache_hit, failure_reason = await service.check_and_fetch_page(
                "https://example.com/install",
                use_semantic_cache=False,
            )

        assert page is fetched_page
        assert is_cache_hit is False
        assert failure_reason is None
        service.fetch_and_cache.assert_awaited_once_with("https://example.com/install")


@pytest.mark.unit
class TestCacheStats:
    """Test cache statistics."""

    @pytest.mark.asyncio
    async def test_get_stats_returns_document_count(self, cache_service):
        """Test getting cache statistics."""
        # Setup: Add some documents
        uow = FakeUnitOfWork()
        async with uow:
            for i in range(3):
                doc = Document.create(
                    url=f"https://example.com/doc{i}",
                    title=f"Doc {i}",
                    markdown=f"# Doc {i}",
                    text=f"Content {i}",
                    excerpt="",
                )
                await uow.documents.add(doc)
            await uow.commit()

        # Act
        stats = await cache_service.get_stats()

        # Assert
        assert stats["documents"] == 3

    @pytest.mark.asyncio
    async def test_get_stats_empty_cache(self, cache_service):
        """Test stats with empty cache."""
        stats = await cache_service.get_stats()
        assert stats["documents"] == 0


@pytest.mark.unit
class TestCacheDocumentErrorPaths:
    """Ensure cache writes fail gracefully for guardrail instrumentation."""

    @pytest.mark.asyncio
    async def test_cache_document_handles_store_errors(self, cache_service):
        page = DocPage(url="https://example.com/failure", title="Failure", content="body", readability_content=None)

        with patch(
            "docs_mcp_server.service_layer.services.store_document",
            AsyncMock(side_effect=RuntimeError("store failure")),
        ) as mock_store:
            success, reason = await cache_service._cache_document(page)

        assert success is False
        assert reason == "cache_store_failed:RuntimeError"
        assert mock_store.await_count == 1


@pytest.mark.unit
class TestSemanticCache:
    """Tests for the semantic cache fallback guardrails."""

    @pytest.mark.asyncio
    async def test_semantic_cache_hit_returns_confident_page(self, mock_settings, uow_factory):
        mock_settings.semantic_cache_enabled = True

        def embed(text: str) -> list[float]:
            return [1.0, 0.0] if "setup" in text or "install" in text else [0.0, 1.0]

        service = CacheService(settings=mock_settings, uow_factory=uow_factory, embedding_provider=embed)

        doc = Document.create(
            url="https://example.com/setup-guide",
            title="Setup Guide",
            markdown="# Setup",
            text="Install everything",
            excerpt="",
        )
        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        hits, confident = await service._get_semantic_cache_hits("https://example.com/install")

        assert confident is True
        assert hits
        assert hits[0].title == "Setup Guide"

    @pytest.mark.asyncio
    async def test_semantic_cache_false_positive_logs_event(self, mock_settings, uow_factory, caplog):
        mock_settings.semantic_cache_enabled = True
        mock_settings.semantic_cache_similarity_threshold = 0.95

        def embed(text: str) -> list[float]:
            return [1.0, 0.0] if "install" in text else [0.0, 1.0]

        service = CacheService(settings=mock_settings, uow_factory=uow_factory, embedding_provider=embed)

        doc = Document.create(
            url="https://example.com/reference",
            title="API Reference",
            markdown="# Ref",
            text="Reference",
            excerpt="",
        )
        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        with caplog.at_level("INFO"):
            hits, confident = await service._get_semantic_cache_hits("https://example.com/install")

        assert hits == []
        assert confident is False
        assert "Semantic cache candidate rejected" in caplog.text

    @pytest.mark.asyncio
    async def test_semantic_cache_ignores_different_hosts(self, mock_settings, uow_factory):
        mock_settings.semantic_cache_enabled = True

        def embed(text: str) -> list[float]:
            return [1.0, 0.0] if "setup" in text else [0.0, 1.0]

        service = CacheService(settings=mock_settings, uow_factory=uow_factory, embedding_provider=embed)

        doc = Document.create(
            url="https://other.example.com/setup-guide",
            title="Setup Guide",
            markdown="# Setup",
            text="Install everything",
            excerpt="",
        )
        uow = FakeUnitOfWork()
        async with uow:
            await uow.documents.add(doc)
            await uow.commit()

        hits, confident = await service._get_semantic_cache_hits("https://example.com/install")

        assert hits == []
        assert confident is False

    @pytest.mark.asyncio
    async def test_semantic_cache_disabled_short_circuits(self, mock_settings, uow_factory):
        """Ensure the semantic cache guardrail short-circuits when disabled."""
        mock_settings.semantic_cache_enabled = False

        service = CacheService(settings=mock_settings, uow_factory=uow_factory)

        hits, confident = await service._get_semantic_cache_hits("https://example.com/any")

        assert hits == []
        assert confident is False
