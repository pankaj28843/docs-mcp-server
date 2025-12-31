"""Unit tests for CacheService offline mode and stale cache behavior."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.domain.model import URL, Content, Document, DocumentMetadata
from docs_mcp_server.service_layer.filesystem_unit_of_work import FakeUnitOfWork
from docs_mcp_server.services.cache_service import CacheService


@pytest.fixture(autouse=True)
def clean_fake_uow():
    """Clear shared state before/after each test."""
    FakeUnitOfWork.clear_shared_store()
    yield
    FakeUnitOfWork.clear_shared_store()


@pytest.fixture
def uow_factory():
    """Factory for creating FakeUnitOfWork instances."""
    return lambda: FakeUnitOfWork()


@pytest.fixture
def offline_settings():
    """Create settings with offline mode enabled."""
    return Settings(
        docs_name="Test Docs",
        docs_entry_url="https://example.com/",
        url_whitelist_prefixes="https://example.com/",
        operation_mode="offline",  # Enables offline mode
        min_fetch_interval_hours=24,
    )


@pytest.fixture
def online_settings():
    """Create settings with online mode enabled."""
    return Settings(
        docs_name="Test Docs",
        docs_sitemap_url="https://example.com/sitemap.xml",
        url_whitelist_prefixes="https://example.com/",
        operation_mode="online",  # Enables online mode
        min_fetch_interval_hours=24,
    )


@pytest.mark.unit
class TestCacheServiceOfflineMode:
    """Test CacheService behavior in offline mode."""

    @pytest.mark.asyncio
    async def test_offline_mode_with_stale_cache(self, offline_settings, uow_factory):
        """Test that stale cache is returned in offline mode."""
        # Create stale cached document (26 hours old, exceeds 24h TTL)
        stale_time = datetime.now(timezone.utc) - timedelta(hours=26)
        metadata = DocumentMetadata(
            last_fetched_at=stale_time,
            status="success",
        )
        doc = Document(
            url=URL(value="https://example.com/stale"),
            title="Stale Doc",
            content=Content(markdown="Stale content", text="Stale content"),
            metadata=metadata,
        )

        async with uow_factory() as uow:
            await uow.documents.add(doc)
            await uow.commit()

        # Create service in offline mode
        cache_service = CacheService(
            settings=offline_settings,
            uow_factory=uow_factory,
        )

        # Should return stale cache in offline mode
        result, is_cached = await cache_service.check_and_fetch_page("https://example.com/stale")

        assert result is not None, "Should return stale cache in offline mode"
        assert result.title == "Stale Doc"
        assert result.content == "Stale content"
        assert is_cached is True

    @pytest.mark.asyncio
    async def test_offline_mode_no_cache_returns_none(self, offline_settings, uow_factory):
        """Test that offline mode returns None when no cache exists."""
        cache_service = CacheService(
            settings=offline_settings,
            uow_factory=uow_factory,
        )

        # Should return None in offline mode with no cache
        result, is_cached = await cache_service.check_and_fetch_page("https://example.com/notfound")

        assert result is None, "Should return None when no cache in offline mode"
        assert is_cached is False

    @pytest.mark.asyncio
    async def test_stale_cache_not_returned_in_online_mode(self, online_settings, uow_factory):
        """Test that stale cache triggers fetch in online mode."""
        # Create stale cached document
        stale_time = datetime.now(timezone.utc) - timedelta(hours=26)
        metadata = DocumentMetadata(
            last_fetched_at=stale_time,
            status="success",
        )
        doc = Document(
            url=URL(value="https://example.com/stale"),
            title="Stale Doc",
            content=Content(markdown="Stale content", text="Stale content"),
            metadata=metadata,
        )

        async with uow_factory() as uow:
            await uow.documents.add(doc)
            await uow.commit()

        # Mock fetcher that returns None (simulating fetch failure)
        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_page = AsyncMock(return_value=None)
            mock_fetcher.__aenter__ = AsyncMock(return_value=mock_fetcher)
            mock_fetcher.__aexit__ = AsyncMock(return_value=None)
            mock_fetcher_class.return_value = mock_fetcher

            cache_service = CacheService(
                settings=online_settings,
                uow_factory=uow_factory,
            )

            # Should try to fetch (and fail) rather than return stale cache
            result, is_cached = await cache_service.check_and_fetch_page("https://example.com/stale")

            # In online mode with fetch failure, should return None
        assert result is None, "Should not return stale cache in online mode when fetch fails"
        assert is_cached is False

    @pytest.mark.asyncio
    async def test_fresh_cache_returned_in_offline_mode(self, offline_settings, uow_factory):
        """Test that fresh cache is returned in offline mode."""
        # Create fresh cached document (12 hours old, within 24h TTL)
        fresh_time = datetime.now(timezone.utc) - timedelta(hours=12)
        metadata = DocumentMetadata(
            last_fetched_at=fresh_time,
            status="success",
        )
        doc = Document(
            url=URL(value="https://example.com/fresh"),
            title="Fresh Doc",
            content=Content(markdown="Fresh content", text="Fresh content"),
            metadata=metadata,
        )

        async with uow_factory() as uow:
            await uow.documents.add(doc)
            await uow.commit()

        cache_service = CacheService(
            settings=offline_settings,
            uow_factory=uow_factory,
        )

        # Should return fresh cache
        result, is_cached = await cache_service.check_and_fetch_page("https://example.com/fresh")

        assert result is not None, "Should return fresh cache"
        assert result.title == "Fresh Doc"
        assert is_cached is True

    @pytest.mark.asyncio
    async def test_offline_mode_does_not_invoke_fetcher_for_stale_cache(self, offline_settings, uow_factory):
        """Ensure offline mode reuses stale cache without calling the fetcher."""
        stale_time = datetime.now(timezone.utc) - timedelta(hours=30)
        metadata = DocumentMetadata(
            last_fetched_at=stale_time,
            status="success",
        )
        doc = Document(
            url=URL(value="https://example.com/offline-stale"),
            title="Offline Stale",
            content=Content(markdown="offline", text="offline"),
            metadata=metadata,
        )

        async with uow_factory() as uow:
            await uow.documents.add(doc)
            await uow.commit()

        with patch("docs_mcp_server.services.cache_service.AsyncDocFetcher") as mock_fetcher_class:
            mock_fetcher = AsyncMock()
            mock_fetcher.fetch_page = AsyncMock()
            mock_fetcher_class.return_value = mock_fetcher

            cache_service = CacheService(settings=offline_settings, uow_factory=uow_factory)
            result, is_cached = await cache_service.check_and_fetch_page("https://example.com/offline-stale")

        assert result is not None
        assert is_cached is True
        mock_fetcher.fetch_page.assert_not_called()
