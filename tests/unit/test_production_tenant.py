"""Unit tests for production-optimized tenant implementation."""

from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.production_tenant import ProductionTenant


@pytest.mark.unit
class TestProductionTenant:
    """Test production-optimized tenant with performance enhancements."""

    @pytest.fixture
    def mock_tenant_config(self):
        """Create mock tenant configuration."""
        config = Mock(spec=TenantConfig)
        config.codename = "test_tenant"
        return config

    @pytest.fixture
    def temp_data_dir(self):
        """Create temporary data directory structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "data" / "test_tenant"
            search_path = data_path / "__search_segments"
            search_path.mkdir(parents=True, exist_ok=True)

            # Create empty search.db file
            search_db = search_path / "search.db"
            search_db.touch()

            yield temp_dir

    def test_init_with_no_search_db(self, mock_tenant_config):
        """Test initialization when search database doesn't exist."""
        tenant = ProductionTenant(mock_tenant_config)

        assert tenant.codename == "test_tenant"
        assert tenant.tenant_config == mock_tenant_config
        assert tenant._search_index is None

    @patch("docs_mcp_server.production_tenant.SIMDSearchIndex")
    def test_init_with_simd_index_success(self, mock_simd_class, mock_tenant_config, temp_data_dir):
        """Test initialization successfully creates SIMD index."""
        mock_simd_instance = Mock()
        mock_simd_class.return_value = mock_simd_instance

        with patch.object(Path, "exists", return_value=True):
            tenant = ProductionTenant(mock_tenant_config)

            assert tenant._search_index == mock_simd_instance
            assert tenant._index_type == "simd"

    @patch("docs_mcp_server.production_tenant.SIMDSearchIndex")
    @patch("docs_mcp_server.production_tenant.LockFreeSearchIndex")
    def test_init_falls_back_to_lockfree(self, mock_lockfree_class, mock_simd_class, mock_tenant_config, temp_data_dir):
        """Test initialization falls back to lock-free index when SIMD fails."""
        mock_simd_class.side_effect = ImportError("No numpy")
        mock_lockfree_instance = Mock()
        mock_lockfree_class.return_value = mock_lockfree_instance

        with patch.object(Path, "exists", return_value=True):
            tenant = ProductionTenant(mock_tenant_config)

            assert tenant._search_index == mock_lockfree_instance
            assert tenant._index_type == "lockfree"

    @patch("docs_mcp_server.production_tenant.SIMDSearchIndex")
    @patch("docs_mcp_server.production_tenant.LockFreeSearchIndex")
    @patch("docs_mcp_server.production_tenant.BloomFilterIndex")
    def test_init_falls_back_to_bloom(
        self, mock_bloom_class, mock_lockfree_class, mock_simd_class, mock_tenant_config, temp_data_dir
    ):
        """Test initialization falls back to bloom filter when others fail."""
        mock_simd_class.side_effect = ImportError("No numpy")
        mock_lockfree_class.side_effect = Exception("Lock-free failed")
        mock_bloom_instance = Mock()
        mock_bloom_class.return_value = mock_bloom_instance

        with patch.object(Path, "exists", return_value=True):
            tenant = ProductionTenant(mock_tenant_config)

            assert tenant._search_index == mock_bloom_instance
            assert tenant._index_type == "bloom"

    def test_search_with_no_index(self, mock_tenant_config):
        """Test search returns error when no search index available."""
        tenant = ProductionTenant(mock_tenant_config)

        result = tenant.search("test query", 10, False)

        assert result.results == []
        assert "No search index" in result.error
        assert result.query == "test query"

    @patch("docs_mcp_server.production_tenant.time.perf_counter")
    @patch("docs_mcp_server.production_tenant.record_search_metrics")
    def test_search_with_index_success(self, mock_record_metrics, mock_perf_counter, mock_tenant_config):
        """Test successful search with metrics recording."""
        # Setup timing
        mock_perf_counter.side_effect = [0.0, 0.001]  # 1ms latency

        # Setup tenant with mock index
        tenant = ProductionTenant(mock_tenant_config)
        mock_search_index = Mock()
        mock_search_response = Mock()
        mock_search_response.results = [
            Mock(document_title="Test Doc", document_url="http://test.com", snippet="test snippet", relevance_score=1.5)
        ]
        mock_search_index.search.return_value = mock_search_response
        tenant._search_index = mock_search_index

        result = tenant.search("test query", 10, False)

        assert len(result.results) == 1
        assert result.results[0].title == "Test Doc"
        assert result.results[0].url == "http://test.com"
        assert result.results[0].score == 1.5
        mock_record_metrics.assert_called_once_with(latency_ms=1.0, result_count=1, query_tokens=2)

    @patch("docs_mcp_server.production_tenant.time.perf_counter")
    @patch("docs_mcp_server.production_tenant.record_search_metrics")
    def test_search_with_index_exception(self, mock_record_metrics, mock_perf_counter, mock_tenant_config):
        """Test search handles exceptions gracefully."""
        # Setup timing
        mock_perf_counter.side_effect = [0.0, 0.002]  # 2ms latency

        # Setup tenant with failing mock index
        tenant = ProductionTenant(mock_tenant_config)
        mock_search_index = Mock()
        mock_search_index.search.side_effect = Exception("Search failed")
        tenant._search_index = mock_search_index

        result = tenant.search("test query", 10, False)

        assert result.results == []
        assert "Search failed" in result.error
        assert result.query == "test query"
        mock_record_metrics.assert_called_once_with(latency_ms=2.0, result_count=0)

    def test_fetch_with_file_uri_success(self, mock_tenant_config):
        """Test fetch successfully reads local file."""
        tenant = ProductionTenant(mock_tenant_config)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as temp_file:
            temp_file.write("Test content")
            temp_file.flush()

            try:
                result = tenant.fetch(f"file://{temp_file.name}", "full")

                assert result.url == f"file://{temp_file.name}"
                assert result.title == Path(temp_file.name).name
                assert result.content == "Test content"
                assert result.context_mode == "full"
            finally:
                Path(temp_file.name).unlink()

    def test_fetch_with_file_uri_not_found(self, mock_tenant_config):
        """Test fetch handles missing file gracefully."""
        tenant = ProductionTenant(mock_tenant_config)

        result = tenant.fetch("file:///nonexistent/file.txt", "full")

        assert result.url == "file:///nonexistent/file.txt"
        assert result.title == ""
        assert result.content == ""
        assert result.error == "Document not found"

    def test_fetch_with_non_file_uri(self, mock_tenant_config):
        """Test fetch handles non-file URIs."""
        tenant = ProductionTenant(mock_tenant_config)

        result = tenant.fetch("http://example.com/doc", "full")

        assert result.url == "http://example.com/doc"
        assert result.title == ""
        assert result.content == ""
        assert result.error == "Document not found"

    def test_browse_tree_returns_not_implemented(self, mock_tenant_config):
        """Test browse_tree returns not implemented error."""
        tenant = ProductionTenant(mock_tenant_config)

        result = tenant.browse_tree("/path", 2)

        assert result.root_path == "/path"
        assert result.depth == 2
        assert result.nodes == []
        assert "Browse not implemented" in result.error

    @patch("docs_mcp_server.production_tenant.get_metrics_collector")
    def test_get_performance_stats(self, mock_get_collector, mock_tenant_config):
        """Test get_performance_stats returns metrics with tenant info."""
        mock_collector = Mock()
        mock_collector.get_stats.return_value = {"searches": 10, "avg_latency": 5.0}
        mock_get_collector.return_value = mock_collector

        tenant = ProductionTenant(mock_tenant_config)
        tenant._index_type = "simd"

        stats = tenant.get_performance_stats()

        assert stats["searches"] == 10
        assert stats["avg_latency"] == 5.0
        assert stats["index_type"] == "simd"
        assert stats["tenant"] == "test_tenant"

    def test_close_closes_search_index(self, mock_tenant_config):
        """Test close method closes search index."""
        tenant = ProductionTenant(mock_tenant_config)
        mock_search_index = Mock()
        tenant._search_index = mock_search_index

        tenant.close()

        mock_search_index.close.assert_called_once()
        assert tenant._search_index is None

    def test_close_with_no_index(self, mock_tenant_config):
        """Test close method handles no search index gracefully."""
        tenant = ProductionTenant(mock_tenant_config)

        # Should not raise exception
        tenant.close()
