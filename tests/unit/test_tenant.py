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
        assert app._documentation_search_engine is not None

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
    async def test_shutdown_closes_documentation_search_engine(self, tenant_config):
        """Test that shutdown closes the documentation search engine."""
        app = TenantApp(tenant_config)

        # Mock the documentation search engine's close method
        app._documentation_search_engine.close = Mock()

        await app.shutdown()
        app._documentation_search_engine.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_delegates_to_documentation_search_engine(self, tenant_config):
        """Test that search delegates to documentation search engine."""
        app = TenantApp(tenant_config)

        # Mock the documentation search engine's search_documents method
        mock_response = Mock()
        app._documentation_search_engine.search_documents = Mock(return_value=mock_response)

        result = await app.search("test query", 10, False)

        app._documentation_search_engine.search_documents.assert_called_once_with("test query", 10, False)
        assert result == mock_response

    @pytest.mark.asyncio
    async def test_fetch_delegates_to_documentation_search_engine(self, tenant_config):
        """Test that fetch delegates to documentation search engine."""
        app = TenantApp(tenant_config)

        # Mock the documentation search engine's fetch_document_content method
        mock_response = Mock()
        app._documentation_search_engine.fetch_document_content = Mock(return_value=mock_response)

        result = await app.fetch("test://uri", "full")

        app._documentation_search_engine.fetch_document_content.assert_called_once_with("test://uri", "full")
        assert result == mock_response

    @pytest.mark.asyncio
    async def test_browse_tree_delegates_to_documentation_search_engine(self, tenant_config):
        """Test that browse_tree delegates to documentation search engine."""
        app = TenantApp(tenant_config)

        # Mock the documentation search engine's browse_document_tree method
        mock_response = Mock()
        app._documentation_search_engine.browse_document_tree = Mock(return_value=mock_response)

        result = await app.browse_tree("/path", 2)

        app._documentation_search_engine.browse_document_tree.assert_called_once_with("/path", 2)
        assert result == mock_response

    def test_get_performance_stats_delegates_to_documentation_search_engine(self, tenant_config):
        """Test that get_performance_stats delegates to documentation search engine."""
        app = TenantApp(tenant_config)

        # Mock the documentation search engine's get_performance_metrics method
        mock_stats = {"tenant": "test", "optimization_level": "basic"}
        app._documentation_search_engine.get_performance_metrics = Mock(return_value=mock_stats)

        result = app.get_performance_stats()

        app._documentation_search_engine.get_performance_metrics.assert_called_once()
        assert result == mock_stats
