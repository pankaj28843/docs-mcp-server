"""Unit tests for simplified tenant architecture."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.tenant import TenantApp, create_tenant_app


@pytest.mark.unit
class TestTenantApp:
    """Test simplified tenant app with direct search index access."""

    @pytest.fixture
    def tenant_config(self, tmp_path: Path):
        """Create test tenant configuration."""
        docs_root = tmp_path / "mcp-data" / "test"
        docs_root.mkdir(parents=True)
        return TenantConfig(
            source_type="filesystem",
            codename="test",
            docs_name="Test Docs",
            docs_root_dir=str(docs_root),
        )

    def test_tenant_app_creation(self, tenant_config):
        """Test that TenantApp can be created with direct search index."""
        app = TenantApp(tenant_config)
        assert app.codename == "test"
        assert app.docs_name == "Test Docs"
        assert app._search_index is None  # No segments directory exists

    def test_create_tenant_app_factory(self, tenant_config):
        """Test the factory function."""
        app = create_tenant_app(tenant_config)
        assert isinstance(app, TenantApp)
        assert app.codename == "test"

    @pytest.mark.asyncio
    async def test_initialize_is_noop(self, tenant_config):
        """Test that initialize is a no-op."""
        app = TenantApp(tenant_config)
        await app.initialize()  # Should not raise

    @pytest.mark.asyncio
    async def test_shutdown_closes_search_index(self, tenant_config):
        """Test that shutdown closes the search index."""
        app = TenantApp(tenant_config)

        # Mock the search index's close method if it exists
        if app._search_index:
            app._search_index.close = Mock()

        await app.shutdown()
        # Should not raise even if no search index

    @pytest.mark.asyncio
    async def test_search_returns_empty_without_index(self, tenant_config):
        """Test that search returns empty response without search index."""
        app = TenantApp(tenant_config)

        result = await app.search("test query", 10, False)

        # Should return empty SearchResponse
        assert result.results == []

    @pytest.mark.asyncio
    async def test_fetch_returns_none_without_index(self, tenant_config):
        """Test that fetch returns error response without search index."""
        app = TenantApp(tenant_config)

        result = await app.fetch("test://uri", "full")

        assert result.error is not None

    @pytest.mark.asyncio
    async def test_browse_tree_returns_empty_without_index(self, tenant_config):
        """Test that browse_tree returns empty response without search index."""
        app = TenantApp(tenant_config)

        result = await app.browse_tree("/path", 2)

        # Should return empty BrowseTreeResponse
        assert result.nodes == []

    def test_get_performance_stats_returns_basic_stats(self, tenant_config):
        """Test that get_performance_stats returns basic stats."""
        app = TenantApp(tenant_config)

        result = app.get_performance_stats()

        assert result["tenant"] == "test"
        assert result["optimization_level"] == "basic"
