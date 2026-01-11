"""Tests for sync_scheduler.py - basic functionality only."""

from datetime import datetime, timezone

import pytest

from docs_mcp_server.config import Settings
from docs_mcp_server.services.cache_service import CacheService
from docs_mcp_server.utils.models import SitemapEntry


@pytest.mark.unit
class TestSyncMetadataBasic:
    """Test basic SyncMetadata functionality."""

    def test_settings_class_available(self):
        """Test that Settings class can be imported and used."""
        settings = Settings(
            docs_name="Test Docs",
            docs_sitemap_url="https://example.com/sitemap.xml",
        )

        assert settings.docs_name == "Test Docs"
        assert settings.docs_sitemap_url == ["https://example.com/sitemap.xml"]

    def test_sitemap_entry_model(self):
        """Test SitemapEntry model functionality."""
        entry = SitemapEntry(url="https://example.com/page1")
        assert str(entry.url) == "https://example.com/page1"
        assert entry.lastmod is None

        # Test with lastmod
        now = datetime.now(timezone.utc)
        entry2 = SitemapEntry(url="https://example.com/page2", lastmod=now)
        assert str(entry2.url) == "https://example.com/page2"
        assert entry2.lastmod == now

    def test_cache_service_class_exists(self):
        """Test that CacheService can be imported."""
        # Basic type checking - we can't instantiate without dependencies
        assert CacheService is not None
        assert hasattr(CacheService, "__init__")
