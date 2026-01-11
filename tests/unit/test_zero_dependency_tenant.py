"""Unit tests for zero dependency tenant implementation."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.utils.models import SearchDocsResponse
from docs_mcp_server.zero_dependency_tenant import ZeroDependencyTenant


@pytest.mark.unit
class TestZeroDependencyTenant:
    """Test zero dependency injection tenant."""

    @pytest.fixture
    def tenant_data(self, tmp_path):
        """Create test tenant data directory."""
        data_dir = tmp_path / "tenant-data"
        data_dir.mkdir()
        return str(data_dir)

    def test_init_with_primitive_parameters(self, tenant_data):
        """Test initialization with primitive parameters only."""
        tenant = ZeroDependencyTenant("test-tenant", tenant_data)

        assert tenant.codename == "test-tenant"
        assert tenant._data_path == Path(tenant_data)

    @patch("docs_mcp_server.zero_dependency_tenant.Path.exists")
    @patch("docs_mcp_server.zero_dependency_tenant.LatencyOptimizedSearchIndex")
    def test_init_creates_search_index_when_db_exists(self, mock_index_class, mock_exists, tenant_data):
        """Test search index creation when database exists."""
        mock_exists.return_value = True
        mock_index = Mock()
        mock_index_class.return_value = mock_index

        tenant = ZeroDependencyTenant("test", tenant_data)

        expected_db_path = Path(tenant_data) / "__search_segments" / "search.db"
        mock_index_class.assert_called_once_with(expected_db_path)
        assert tenant._search_index is mock_index

    @patch("docs_mcp_server.zero_dependency_tenant.Path.exists")
    def test_init_no_search_index_when_db_missing(self, mock_exists, tenant_data):
        """Test no search index when database doesn't exist."""
        mock_exists.return_value = False

        tenant = ZeroDependencyTenant("test", tenant_data)

        assert tenant._search_index is None

    def test_search_without_index_returns_error(self, tenant_data):
        """Test search returns error when no index available."""
        tenant = ZeroDependencyTenant("test", tenant_data)
        tenant._search_index = None

        result = tenant.search("test query", 10, False)

        assert isinstance(result, SearchDocsResponse)
        assert result.results == []
        assert result.error == "No search index for test"
        assert result.query == "test query"

    def test_search_with_index_delegates_directly(self, tenant_data):
        """Test search delegates directly to index without service layers."""
        mock_index = Mock()
        mock_search_result = Mock()
        mock_search_result.results = [Mock(title="Test", url="test://url", snippet="snippet", score=1.0)]
        mock_index.search.return_value = mock_search_result

        tenant = ZeroDependencyTenant("test", tenant_data)
        tenant._search_index = mock_index

        result = tenant.search("test query", 5, True)

        # Verify direct call without service orchestration
        mock_index.search.assert_called_once_with("test query", 5)
        assert isinstance(result, SearchDocsResponse)
        assert len(result.results) == 1

    def test_search_ignores_word_match_parameter(self, tenant_data):
        """Test search ignores word_match parameter."""
        mock_index = Mock()
        mock_search_result = Mock()
        mock_search_result.results = []
        mock_index.search.return_value = mock_search_result

        tenant = ZeroDependencyTenant("test", tenant_data)
        tenant._search_index = mock_index

        # Both word_match values should result in same call
        tenant.search("query", 10, True)
        mock_index.search.assert_called_with("query", 10)

        mock_index.reset_mock()
        tenant.search("query", 10, False)
        mock_index.search.assert_called_with("query", 10)

    def test_search_handles_index_exception(self, tenant_data):
        """Test search handles exceptions from index."""
        mock_index = Mock()
        mock_index.search.side_effect = Exception("Index error")

        tenant = ZeroDependencyTenant("test", tenant_data)
        tenant._search_index = mock_index

        result = tenant.search("query", 10, False)

        assert isinstance(result, SearchDocsResponse)
        assert result.results == []
        assert "Index error" in result.error

    def test_search_converts_results_correctly(self, tenant_data):
        """Test search converts index results to response format."""
        mock_result = Mock()
        mock_result.title = "Test Document"
        mock_result.url = "test://document"
        mock_result.snippet = "Test snippet"
        mock_result.score = 0.95

        mock_index = Mock()
        mock_search_result = Mock()
        mock_search_result.results = [mock_result]
        mock_index.search.return_value = mock_search_result

        tenant = ZeroDependencyTenant("test", tenant_data)
        tenant._search_index = mock_index

        result = tenant.search("query", 10, False)

        assert len(result.results) == 1
        assert result.results[0].title == "Test Document"
        assert result.results[0].url == "test://document"
        assert result.error is None

    def test_eliminates_dependency_injection_patterns(self, tenant_data):
        """Test that all DI patterns are eliminated."""
        tenant = ZeroDependencyTenant("test", tenant_data)

        # Verify no DI containers or interfaces
        assert not hasattr(tenant, "_service_container")
        assert not hasattr(tenant, "_injector")
        assert not hasattr(tenant, "_factory")
        assert not hasattr(tenant, "_services")

        # Verify direct instantiation pattern
        assert hasattr(tenant, "codename")
        assert hasattr(tenant, "_data_path")
        assert hasattr(tenant, "_search_index")

    def test_uses_concrete_classes_only(self, tenant_data):
        """Test uses concrete classes, no interfaces."""
        tenant = ZeroDependencyTenant("test", tenant_data)

        # Verify concrete types, not interfaces
        assert isinstance(tenant.codename, str)
        assert isinstance(tenant._data_path, Path)

    def test_primitive_configuration_parameters(self, tenant_data):
        """Test uses primitive configuration parameters only."""
        # Constructor should only accept primitive types
        tenant = ZeroDependencyTenant("test-name", tenant_data)

        assert isinstance(tenant.codename, str)
        assert isinstance(str(tenant._data_path), str)

    def test_raii_resource_management(self, tenant_data):
        """Test RAII (Resource Acquisition Is Initialization) pattern."""
        # Resources should be acquired during initialization
        with patch("docs_mcp_server.zero_dependency_tenant.Path.exists", return_value=True):
            with patch("docs_mcp_server.zero_dependency_tenant.LatencyOptimizedSearchIndex") as mock_index:
                mock_index.return_value = Mock()

                tenant = ZeroDependencyTenant("test", tenant_data)

                # Resource acquired during init
                assert tenant._search_index is not None
                mock_index.assert_called_once()

    def test_data_path_construction(self, tenant_data):
        """Test data path is constructed correctly."""
        tenant = ZeroDependencyTenant("test", tenant_data)

        assert tenant._data_path == Path(tenant_data)

    def test_search_db_path_construction(self, tenant_data):
        """Test search database path construction."""
        with patch("docs_mcp_server.zero_dependency_tenant.Path.exists") as mock_exists:
            with patch("docs_mcp_server.zero_dependency_tenant.LatencyOptimizedSearchIndex") as mock_index:
                mock_exists.return_value = True
                mock_index.return_value = Mock()

                ZeroDependencyTenant("test", tenant_data)

                expected_path = Path(tenant_data) / "__search_segments" / "search.db"
                mock_index.assert_called_once_with(expected_path)

    def test_no_service_orchestration(self, tenant_data):
        """Test eliminates service orchestration layers."""
        mock_index = Mock()
        mock_index.search.return_value = Mock(results=[])

        tenant = ZeroDependencyTenant("test", tenant_data)
        tenant._search_index = mock_index

        # Direct execution without service layers
        tenant.search("query", 10, False)

        # Should be direct call, no intermediate service calls
        mock_index.search.assert_called_once_with("query", 10)
