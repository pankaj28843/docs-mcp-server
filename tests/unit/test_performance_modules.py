"""Minimal tests for new performance modules."""

from unittest.mock import patch

import pytest

from docs_mcp_server.deployment_config import TenantConfig
from docs_mcp_server.production_tenant import ProductionTenant
from docs_mcp_server.search.metrics import MetricsCollector, SearchMetrics


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

    def test_search_without_index(self, tenant_config):
        """Test search when no index is available."""
        tenant = ProductionTenant(tenant_config)
        result = tenant.search("test query", 10, False)

        assert result.error == "No search index for test"
        assert result.results == []

    def test_fetch_non_file_url(self, tenant_config):
        """Test fetching non-file URL."""
        tenant = ProductionTenant(tenant_config)
        result = tenant.fetch("https://example.com", None)

        assert result.error == "Document not found"

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

    def test_get_stats_empty(self):
        """Test getting stats when no metrics recorded."""
        collector = MetricsCollector()
        stats = collector.get_stats()
        assert stats == {}

    def test_reset(self):
        """Test resetting metrics."""
        collector = MetricsCollector()

        # Add some data
        metrics = SearchMetrics(5.0, 2.0, 10.0, 5, 1, 3, 2)
        collector.record_search(metrics)

        collector.reset()

        assert len(collector._metrics) == 0
        assert len(collector._counters) == 0
