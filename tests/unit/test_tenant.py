"""Unit tests for simplified production tenant architecture."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.tenant import TenantApp, create_tenant_app


@pytest.mark.unit
class TestTenantApp:
    """Test simplified tenant app."""

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
        """Test that TenantApp can be created."""
        app = TenantApp(tenant_config)
        assert app.codename == "test"
        assert app.docs_name == "Test Docs"
        assert app._production_tenant is not None

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
    async def test_shutdown_closes_production_tenant(self, tenant_config):
        """Test that shutdown closes the production tenant."""
        app = TenantApp(tenant_config)

        # Mock the production tenant's close method
        app._production_tenant.close = Mock()

        await app.shutdown()
        app._production_tenant.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_delegates_to_production_tenant(self, tenant_config):
        """Test that search delegates to production tenant."""
        app = TenantApp(tenant_config)

        # Mock the production tenant's search method
        mock_response = Mock()
        app._production_tenant.search = Mock(return_value=mock_response)

        result = await app.search("test query", 10, False)

        app._production_tenant.search.assert_called_once_with("test query", 10, False)
        assert result == mock_response

    @pytest.mark.asyncio
    async def test_fetch_delegates_to_production_tenant(self, tenant_config):
        """Test that fetch delegates to production tenant."""
        app = TenantApp(tenant_config)

        # Mock the production tenant's fetch method
        mock_response = Mock()
        app._production_tenant.fetch = Mock(return_value=mock_response)

        result = await app.fetch("test://uri", "full")

        app._production_tenant.fetch.assert_called_once_with("test://uri", "full")
        assert result == mock_response

    @pytest.mark.asyncio
    async def test_browse_tree_delegates_to_production_tenant(self, tenant_config):
        """Test that browse_tree delegates to production tenant."""
        app = TenantApp(tenant_config)

        # Mock the production tenant's browse_tree method
        mock_response = Mock()
        app._production_tenant.browse_tree = Mock(return_value=mock_response)

        result = await app.browse_tree("/path", 2)

        app._production_tenant.browse_tree.assert_called_once_with("/path", 2)
        assert result == mock_response

    def test_get_performance_stats_delegates_to_production_tenant(self, tenant_config):
        """Test that get_performance_stats delegates to production tenant."""
        app = TenantApp(tenant_config)

        # Mock the production tenant's get_performance_stats method
        mock_stats = {"tenant": "test", "index_type": "simd"}
        app._production_tenant.get_performance_stats = Mock(return_value=mock_stats)

        result = app.get_performance_stats()

        app._production_tenant.get_performance_stats.assert_called_once()
        assert result == mock_stats
