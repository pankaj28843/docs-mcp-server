"""Comprehensive tests for new performance modules."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.production_tenant import ProductionTenant
from docs_mcp_server.search.bloom_index import BloomFilterIndex
from docs_mcp_server.search.lockfree_index import LockFreeSearchIndex
from docs_mcp_server.search.metrics import MetricsCollector, SearchMetrics, get_metrics_collector, record_search_metrics
from docs_mcp_server.search.simd_index import SIMDSearchIndex


@pytest.fixture
def tenant_config():
    return TenantConfig(
        codename="test",
        docs_name="Test Docs",
        source_type="filesystem",
        docs_root_dir="/tmp/test",
    )


class TestProductionTenant:
    def test_init_without_search_db(self, tenant_config):
        """Test initialization when search DB doesn't exist."""
        tenant = ProductionTenant(tenant_config)
        assert tenant.codename == "test"
        assert tenant._search_index is None

    @patch("docs_mcp_server.production_tenant.Path.exists")
    @patch("docs_mcp_server.production_tenant.SIMDSearchIndex")
    def test_init_with_simd_index(self, mock_simd, mock_exists, tenant_config):
        """Test initialization with SIMD index."""
        mock_exists.return_value = True
        mock_simd.return_value = Mock()

        tenant = ProductionTenant(tenant_config)

        mock_simd.assert_called_once()
        assert tenant._index_type == "simd"

    @patch("docs_mcp_server.production_tenant.Path.exists")
    @patch("docs_mcp_server.production_tenant.SIMDSearchIndex", side_effect=ImportError)
    @patch("docs_mcp_server.production_tenant.LockFreeSearchIndex")
    def test_init_fallback_to_lockfree(self, mock_lockfree, mock_simd, mock_exists, tenant_config):
        """Test fallback to lock-free index."""
        mock_exists.return_value = True
        mock_lockfree.return_value = Mock()

        tenant = ProductionTenant(tenant_config)

        mock_lockfree.assert_called_once()
        assert tenant._index_type == "lockfree"

    @patch("docs_mcp_server.production_tenant.Path.exists")
    @patch("docs_mcp_server.production_tenant.SIMDSearchIndex", side_effect=ImportError)
    @patch("docs_mcp_server.production_tenant.LockFreeSearchIndex", side_effect=Exception)
    @patch("docs_mcp_server.production_tenant.BloomFilterIndex")
    def test_init_fallback_to_bloom(self, mock_bloom, mock_lockfree, mock_simd, mock_exists, tenant_config):
        """Test fallback to Bloom filter index."""
        mock_exists.return_value = True
        mock_bloom.return_value = Mock()

        tenant = ProductionTenant(tenant_config)

        mock_bloom.assert_called_once()
        assert tenant._index_type == "bloom"

    def test_search_without_index(self, tenant_config):
        """Test search when no index is available."""
        tenant = ProductionTenant(tenant_config)
        result = tenant.search("test query", 10, False)

        assert result.error == "No search index for test"
        assert result.results == []

    @patch("docs_mcp_server.production_tenant.time")
    @patch("docs_mcp_server.production_tenant.record_search_metrics")
    def test_search_with_index(self, mock_metrics, mock_time, tenant_config):
        """Test successful search with metrics."""
        mock_time.perf_counter.side_effect = [0.0, 0.001]

        mock_search_index = Mock()
        mock_result = Mock()
        # Create a proper mock result with actual values, not Mock objects
        mock_search_result = Mock()
        mock_search_result.document_title = "Test"
        mock_search_result.document_url = "test://url"
        mock_search_result.snippet = "snippet"
        mock_search_result.relevance_score = 1.0
        mock_result.results = [mock_search_result]
        mock_search_index.search.return_value = mock_result

        tenant = ProductionTenant(tenant_config)
        tenant._search_index = mock_search_index

        result = tenant.search("test query", 10, False)

        mock_search_index.search.assert_called_once_with("test query", 10)
        mock_metrics.assert_called_once()
        assert len(result.results) == 1

    @patch("docs_mcp_server.production_tenant.time")
    @patch("docs_mcp_server.production_tenant.record_search_metrics")
    def test_search_with_exception(self, mock_metrics, mock_time, tenant_config):
        """Test search with exception handling."""
        mock_time.perf_counter.side_effect = [0.0, 0.001]

        mock_search_index = Mock()
        mock_search_index.search.side_effect = Exception("Search failed")

        tenant = ProductionTenant(tenant_config)
        tenant._search_index = mock_search_index

        result = tenant.search("test query", 10, False)

        assert "Search failed" in result.error
        mock_metrics.assert_called_once()

    def test_fetch_file_url(self, tenant_config, tmp_path):
        """Test fetching file URL."""
        test_file = tmp_path / "test.md"
        test_file.write_text("# Test Content")

        tenant = ProductionTenant(tenant_config)
        result = tenant.fetch(f"file://{test_file}", None)

        assert result.error is None
        assert result.title == "test.md"
        assert "Test Content" in result.content

    def test_fetch_missing_file(self, tenant_config):
        """Test fetching missing file."""
        tenant = ProductionTenant(tenant_config)
        result = tenant.fetch("file:///nonexistent.md", None)

        assert result.error == "Document not found"

    def test_fetch_non_file_url(self, tenant_config):
        """Test fetching non-file URL."""
        tenant = ProductionTenant(tenant_config)
        result = tenant.fetch("https://example.com", None)

        assert result.error == "Document not found"

    def test_fetch_file_read_error(self, tenant_config, tmp_path):
        """Test fetch with file read error."""
        test_file = tmp_path / "test.md"
        test_file.write_text("content")

        tenant = ProductionTenant(tenant_config)

        with patch("pathlib.Path.read_text", side_effect=OSError("Permission denied")):
            result = tenant.fetch(f"file://{test_file}", None)
            assert "Failed to read file" in result.error

    def test_browse_tree(self, tenant_config):
        """Test browse tree returns not implemented."""
        tenant = ProductionTenant(tenant_config)
        result = tenant.browse_tree("/", 2)

        assert "Browse not implemented" in result.error
        assert result.nodes == []

    @patch("docs_mcp_server.production_tenant.get_metrics_collector")
    def test_get_performance_stats(self, mock_collector, tenant_config):
        """Test getting performance stats."""
        mock_collector.return_value.get_stats.return_value = {"searches": 10}

        tenant = ProductionTenant(tenant_config)
        tenant._index_type = "simd"

        stats = tenant.get_performance_stats()

        assert stats["searches"] == 10
        assert stats["index_type"] == "simd"
        assert stats["tenant"] == "test"

    def test_get_performance_stats_no_index_type(self, tenant_config):
        """Test performance stats without index type."""
        with patch("docs_mcp_server.production_tenant.get_metrics_collector") as mock_collector:
            mock_collector.return_value.get_stats.return_value = {"searches": 5}

            tenant = ProductionTenant(tenant_config)
            stats = tenant.get_performance_stats()

            assert stats["index_type"] == "none"

    def test_close_with_index(self, tenant_config):
        """Test closing tenant with index."""
        mock_search_index = Mock()

        tenant = ProductionTenant(tenant_config)
        tenant._search_index = mock_search_index

        tenant.close()

        mock_search_index.close.assert_called_once()
        assert tenant._search_index is None

    def test_close_without_index(self, tenant_config):
        """Test closing tenant without index."""
        tenant = ProductionTenant(tenant_config)
        tenant.close()  # Should not raise


class TestSearchMetrics:
    def test_search_metrics_creation(self):
        """Test SearchMetrics dataclass creation."""
        metrics = SearchMetrics(
            latency_ms=10.5,
            memory_mb=5.2,
            cpu_percent=15.0,
            cache_hits=10,
            cache_misses=2,
            result_count=5,
            query_tokens=3,
        )

        assert metrics.latency_ms == 10.5
        assert metrics.memory_mb == 5.2
        assert metrics.result_count == 5

    def test_metrics_collector_init(self):
        """Test MetricsCollector initialization."""
        collector = MetricsCollector(window_size=100)
        assert collector.window_size == 100
        assert len(collector._metrics) == 0

    def test_start_end_timer(self):
        """Test timer functionality."""
        collector = MetricsCollector()

        timer_id = collector.start_timer("search")
        assert timer_id in collector._timers

        duration = collector.end_timer(timer_id)
        assert duration >= 0
        assert timer_id not in collector._timers

    def test_end_timer_nonexistent(self):
        """Test ending nonexistent timer."""
        collector = MetricsCollector()
        duration = collector.end_timer("nonexistent")
        assert duration == 0.0

    def test_record_search(self):
        """Test recording search metrics."""
        collector = MetricsCollector()
        metrics = SearchMetrics(
            latency_ms=5.0,
            memory_mb=2.0,
            cpu_percent=10.0,
            cache_hits=5,
            cache_misses=1,
            result_count=3,
            query_tokens=2,
        )

        collector.record_search(metrics)

        assert len(collector._metrics) == 1
        assert collector._counters["total_searches"] == 1

    def test_record_search_slow(self):
        """Test recording slow search."""
        collector = MetricsCollector()
        metrics = SearchMetrics(
            latency_ms=15.0,  # > 10ms threshold
            memory_mb=2.0,
            cpu_percent=10.0,
            cache_hits=5,
            cache_misses=1,
            result_count=3,
            query_tokens=2,
        )

        collector.record_search(metrics)

        assert collector._counters["slow_searches"] == 1

    def test_record_search_empty_results(self):
        """Test recording search with empty results."""
        collector = MetricsCollector()
        metrics = SearchMetrics(
            latency_ms=5.0,
            memory_mb=2.0,
            cpu_percent=10.0,
            cache_hits=5,
            cache_misses=1,
            result_count=0,  # Empty results
            query_tokens=2,
        )

        collector.record_search(metrics)

        assert collector._counters["empty_results"] == 1

    def test_get_stats_empty(self):
        """Test getting stats when no metrics recorded."""
        collector = MetricsCollector()
        stats = collector.get_stats()
        assert stats == {}

    def test_get_stats_with_metrics(self):
        """Test getting stats with recorded metrics."""
        collector = MetricsCollector()

        # Record multiple metrics
        for i in range(5):
            metrics = SearchMetrics(
                latency_ms=float(i + 1),
                memory_mb=float(i + 1),
                cpu_percent=10.0,
                cache_hits=5,
                cache_misses=1,
                result_count=i,
                query_tokens=2,
            )
            collector.record_search(metrics)

        stats = collector.get_stats()

        assert stats["count"] == 5
        assert "latency" in stats
        assert "memory" in stats
        assert "results" in stats
        assert "performance" in stats

        assert stats["latency"]["mean"] == 3.0  # (1+2+3+4+5)/5
        assert stats["latency"]["max"] == 5.0

    def test_reset(self):
        """Test resetting metrics."""
        collector = MetricsCollector()

        # Add some data
        collector.start_timer("test")
        metrics = SearchMetrics(5.0, 2.0, 10.0, 5, 1, 3, 2)
        collector.record_search(metrics)

        collector.reset()

        assert len(collector._metrics) == 0
        assert len(collector._counters) == 0
        assert len(collector._timers) == 0


class TestGlobalFunctions:
    def test_get_metrics_collector(self):
        """Test getting global metrics collector."""

        collector = get_metrics_collector()
        assert isinstance(collector, MetricsCollector)

        # Should return same instance
        collector2 = get_metrics_collector()
        assert collector is collector2

    def test_record_search_metrics(self):
        """Test convenience function for recording metrics."""

        collector = get_metrics_collector()
        collector.reset()  # Clear any existing metrics

        record_search_metrics(latency_ms=10.0, memory_mb=5.0, result_count=3, query_tokens=2)

        stats = collector.get_stats()
        assert stats["count"] == 1
        assert stats["latency"]["mean"] == 10.0


# Test search index imports and basic functionality
class TestSearchIndexes:
    @patch("docs_mcp_server.search.simd_index.sqlite3")
    @patch("docs_mcp_server.search.simd_index.get_analyzer")
    def test_simd_index_basic(self, mock_analyzer, mock_sqlite):
        """Test SIMD index basic functionality."""

        mock_conn = Mock()
        mock_sqlite.connect.return_value = mock_conn
        mock_analyzer.return_value = Mock()

        index = SIMDSearchIndex(Path("/tmp/test.db"))
        assert index.db_path == Path("/tmp/test.db")

        # Test close
        index.close()
        mock_conn.close.assert_called_once()

    @patch("docs_mcp_server.search.bloom_index.sqlite3")
    @patch("docs_mcp_server.search.bloom_index.get_analyzer")
    def test_bloom_index_basic(self, mock_analyzer, mock_sqlite):
        """Test Bloom index basic functionality."""

        mock_conn = Mock()
        mock_cursor = Mock()
        mock_cursor.__iter__ = Mock(return_value=iter([]))
        mock_conn.execute.return_value = mock_cursor
        mock_sqlite.connect.return_value = mock_conn
        mock_analyzer.return_value = Mock()

        index = BloomFilterIndex(Path("/tmp/test.db"))
        assert index.db_path == Path("/tmp/test.db")

        # Test close
        index.close()
        mock_conn.close.assert_called_once()

    @patch("docs_mcp_server.search.lockfree_index.sqlite3")
    @patch("docs_mcp_server.search.lockfree_index.get_analyzer")
    def test_lockfree_index_basic(self, mock_analyzer, mock_sqlite):
        """Test lock-free index basic functionality."""

        mock_conn = Mock()
        mock_sqlite.connect.return_value = mock_conn
        mock_analyzer.return_value = Mock()

        index = LockFreeSearchIndex(Path("/tmp/test.db"))
        assert index.db_path == Path("/tmp/test.db")

        # Test close - LockFreeSearchIndex only shuts down executor
        index.close()
        # No connection close assertion since it's not called
