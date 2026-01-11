"""Unit tests for simplified tenant implementation."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.simple_tenant import SimpleTenantApp
from docs_mcp_server.utils.models import SearchDocsResponse


@pytest.mark.unit
class TestSimpleTenantApp:
    """Test simplified tenant app with direct construction."""

    @pytest.fixture
    def tenant_config(self):
        """Create test tenant configuration."""
        return TenantConfig(
            codename="test-tenant",
            docs_name="Test Documentation",
            source_type="filesystem",
            docs_root_dir="/tmp/test-docs",
        )

    def test_init_stores_config_and_codename(self, tenant_config):
        """Test initialization stores configuration and codename."""
        app = SimpleTenantApp(tenant_config)

        assert app.tenant_config is tenant_config
        assert app.codename == "test-tenant"

    @patch("docs_mcp_server.simple_tenant.Path.exists")
    @patch("docs_mcp_server.simple_tenant.SearchIndex")
    def test_init_creates_search_index_when_db_exists(self, mock_search_index, mock_exists, tenant_config):
        """Test search index creation when database exists."""
        mock_exists.return_value = True
        mock_index_instance = Mock()
        mock_search_index.return_value = mock_index_instance

        app = SimpleTenantApp(tenant_config)

        expected_db_path = Path("data/test-tenant/__search_segments/search.db")
        mock_exists.assert_called_once_with()
        mock_search_index.assert_called_once_with(expected_db_path)
        assert app._search_index is mock_index_instance

    @patch("docs_mcp_server.simple_tenant.Path.exists")
    def test_init_no_search_index_when_db_missing(self, mock_exists, tenant_config):
        """Test no search index when database doesn't exist."""
        mock_exists.return_value = False

        app = SimpleTenantApp(tenant_config)

        assert app._search_index is None

    def test_get_search_db_path_returns_correct_path(self, tenant_config):
        """Test search database path construction."""
        app = SimpleTenantApp(tenant_config)

        db_path = app._get_search_db_path()

        expected_path = Path("data/test-tenant/__search_segments/search.db")
        assert db_path == expected_path

    @pytest.mark.asyncio
    async def test_search_without_index_returns_error(self, tenant_config):
        """Test search returns error when no index available."""
        app = SimpleTenantApp(tenant_config)
        app._search_index = None

        result = await app.search("test query", 10, False)

        assert isinstance(result, SearchDocsResponse)
        assert result.results == []
        assert "No search index" in result.error
        assert result.query == "test query"

    @pytest.mark.asyncio
    async def test_search_with_index_delegates_to_index(self, tenant_config):
        """Test search delegates to search index when available."""
        mock_index = Mock()
        mock_search_result = Mock()
        mock_search_result.results = [Mock(title="Test", url="test://url", snippet="snippet", score=1.0)]
        mock_index.search.return_value = mock_search_result

        app = SimpleTenantApp(tenant_config)
        app._search_index = mock_index

        result = await app.search("test query", 5, True)

        mock_index.search.assert_called_once_with("test query", 5)
        assert isinstance(result, SearchDocsResponse)
        assert len(result.results) == 1

    @pytest.mark.asyncio
    async def test_search_ignores_word_match_parameter(self, tenant_config):
        """Test search ignores word_match parameter in simplified implementation."""
        mock_index = Mock()
        mock_search_result = Mock()
        mock_search_result.results = []
        mock_index.search.return_value = mock_search_result

        app = SimpleTenantApp(tenant_config)
        app._search_index = mock_index

        # word_match=True should be ignored
        await app.search("test", 10, True)
        mock_index.search.assert_called_once_with("test", 10)

        # word_match=False should also be ignored
        mock_index.reset_mock()
        await app.search("test", 10, False)
        mock_index.search.assert_called_once_with("test", 10)

    @pytest.mark.asyncio
    async def test_search_handles_index_exception(self, tenant_config):
        """Test search handles exceptions from search index."""
        mock_index = Mock()
        mock_index.search.side_effect = Exception("Search failed")

        app = SimpleTenantApp(tenant_config)
        app._search_index = mock_index

        result = await app.search("test query", 10, False)

        assert isinstance(result, SearchDocsResponse)
        assert result.results == []
        assert "Search failed" in result.error

    @pytest.mark.asyncio
    async def test_search_converts_index_results_to_response(self, tenant_config):
        """Test search converts index results to SearchDocsResponse."""
        mock_result_1 = Mock()
        mock_result_1.title = "Doc 1"
        mock_result_1.url = "test://doc1"
        mock_result_1.snippet = "First document"
        mock_result_1.score = 0.9

        mock_result_2 = Mock()
        mock_result_2.title = "Doc 2"
        mock_result_2.url = "test://doc2"
        mock_result_2.snippet = "Second document"
        mock_result_2.score = 0.8

        mock_index = Mock()
        mock_search_result = Mock()
        mock_search_result.results = [mock_result_1, mock_result_2]
        mock_index.search.return_value = mock_search_result

        app = SimpleTenantApp(tenant_config)
        app._search_index = mock_index

        result = await app.search("test", 10, False)

        assert len(result.results) == 2
        assert result.results[0].title == "Doc 1"
        assert result.results[1].title == "Doc 2"
        assert result.error is None

    def test_direct_construction_eliminates_di_complexity(self, tenant_config):
        """Test direct construction eliminates dependency injection complexity."""
        # This test verifies the architectural principle
        app = SimpleTenantApp(tenant_config)

        # Verify no service containers or factories used
        assert not hasattr(app, "_service_container")
        assert not hasattr(app, "_factory")
        assert not hasattr(app, "_injector")

        # Verify direct construction pattern
        assert hasattr(app, "_search_index")
        assert hasattr(app, "tenant_config")
        assert hasattr(app, "codename")

    @patch("docs_mcp_server.simple_tenant.Path.exists")
    def test_search_db_path_uses_codename(self, mock_exists, tenant_config):
        """Test search database path incorporates tenant codename."""
        mock_exists.return_value = False
        tenant_config.codename = "custom-name"

        app = SimpleTenantApp(tenant_config)

        db_path = app._get_search_db_path()
        assert "custom-name" in str(db_path)
        assert str(db_path).startswith("data/custom-name/")
