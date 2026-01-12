"""Unit tests for search metrics collection."""

from unittest.mock import patch

import pytest

from docs_mcp_server.search.metrics import (
    MetricsCollector,
    SearchMetrics,
    get_metrics_collector,
    record_search_metrics,
)


@pytest.mark.unit
class TestSearchMetrics:
    """Test SearchMetrics dataclass."""

    def test_search_metrics_creation(self):
        """Test SearchMetrics can be created with all fields."""
        metrics = SearchMetrics(
            latency_ms=10.5,
            memory_mb=2.3,
            cpu_percent=15.0,
            cache_hits=5,
            cache_misses=2,
            result_count=10,
            query_tokens=3,
        )

        assert metrics.latency_ms == 10.5
        assert metrics.memory_mb == 2.3
        assert metrics.cpu_percent == 15.0
        assert metrics.cache_hits == 5
        assert metrics.cache_misses == 2
        assert metrics.result_count == 10
        assert metrics.query_tokens == 3


@pytest.mark.unit
class TestMetricsCollector:
    """Test MetricsCollector functionality."""

    @pytest.fixture
    def collector(self):
        """Create fresh metrics collector."""
        return MetricsCollector(window_size=100)

    def test_init_default_window_size(self):
        """Test initialization with default window size."""
        collector = MetricsCollector()
        assert collector.window_size == 1000

    def test_init_custom_window_size(self):
        """Test initialization with custom window size."""
        collector = MetricsCollector(window_size=500)
        assert collector.window_size == 500

    @patch("docs_mcp_server.search.metrics.time")
    def test_start_timer(self, mock_time, collector):
        """Test starting a timer."""
        mock_time.time.return_value = 1234567890.0
        mock_time.perf_counter.return_value = 100.0

        timer_id = collector.start_timer("search")

        assert timer_id == "search_1234567890.0"
        assert collector._timers[timer_id] == 100.0

    @patch("docs_mcp_server.search.metrics.time")
    def test_end_timer_success(self, mock_time, collector):
        """Test ending a timer successfully."""
        mock_time.perf_counter.side_effect = [100.0, 105.0]

        timer_id = collector.start_timer("search")
        duration = collector.end_timer(timer_id)

        assert duration == 5000.0  # 5 seconds * 1000 = 5000ms
        assert timer_id not in collector._timers

    def test_end_timer_missing(self, collector):
        """Test ending a non-existent timer."""
        duration = collector.end_timer("missing_timer")
        assert duration == 0.0

    def test_record_search_basic(self, collector):
        """Test recording basic search metrics."""
        metrics = SearchMetrics(
            latency_ms=10.0,
            memory_mb=1.0,
            cpu_percent=5.0,
            cache_hits=2,
            cache_misses=1,
            result_count=5,
            query_tokens=2,
        )

        collector.record_search(metrics)

        assert len(collector._metrics) == 1
        assert collector._counters["total_searches"] == 1
        assert collector._counters["slow_searches"] == 0
        assert collector._counters["empty_results"] == 0

    def test_record_search_slow(self, collector):
        """Test recording slow search metrics."""
        metrics = SearchMetrics(
            latency_ms=15.0,  # > 10ms threshold
            memory_mb=1.0,
            cpu_percent=5.0,
            cache_hits=2,
            cache_misses=1,
            result_count=5,
            query_tokens=2,
        )

        collector.record_search(metrics)

        assert collector._counters["slow_searches"] == 1

    def test_record_search_empty_results(self, collector):
        """Test recording search with empty results."""
        metrics = SearchMetrics(
            latency_ms=5.0,
            memory_mb=1.0,
            cpu_percent=5.0,
            cache_hits=2,
            cache_misses=1,
            result_count=0,  # Empty results
            query_tokens=2,
        )

        collector.record_search(metrics)

        assert collector._counters["empty_results"] == 1

    def test_get_stats_empty(self, collector):
        """Test getting stats with no metrics."""
        stats = collector.get_stats()
        assert stats == {}

    def test_get_stats_with_metrics(self, collector):
        """Test getting stats with recorded metrics."""
        # Record multiple metrics
        metrics1 = SearchMetrics(5.0, 1.0, 10.0, 1, 0, 3, 2)
        metrics2 = SearchMetrics(15.0, 2.0, 20.0, 2, 1, 0, 3)
        metrics3 = SearchMetrics(8.0, 1.5, 15.0, 1, 1, 5, 1)

        collector.record_search(metrics1)
        collector.record_search(metrics2)
        collector.record_search(metrics3)

        stats = collector.get_stats()

        assert stats["count"] == 3
        assert stats["latency"]["mean"] == pytest.approx(9.33, rel=1e-2)
        assert stats["latency"]["max"] == 15.0
        assert stats["memory"]["mean"] == pytest.approx(1.5, rel=1e-2)
        assert stats["memory"]["max"] == 2.0
        assert stats["results"]["mean"] == pytest.approx(2.67, rel=1e-2)
        assert stats["results"]["empty_rate"] == pytest.approx(1 / 3, rel=1e-2)
        assert stats["performance"]["slow_rate"] == pytest.approx(1 / 3, rel=1e-2)
        assert stats["performance"]["total_searches"] == 3

    def test_get_stats_percentiles(self, collector):
        """Test percentile calculations in stats."""
        # Record metrics with known latencies for percentile testing
        latencies = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        for latency in latencies:
            metrics = SearchMetrics(latency, 1.0, 10.0, 1, 0, 1, 1)
            collector.record_search(metrics)

        stats = collector.get_stats()

        # For 10 items, p95 = index 9 (95% of 10), p99 = index 9 (99% of 10)
        assert stats["latency"]["p95"] == 10.0
        assert stats["latency"]["p99"] == 10.0

    def test_window_size_limit(self):
        """Test metrics window size limit."""
        collector = MetricsCollector(window_size=2)

        # Add 3 metrics, should only keep last 2
        for i in range(3):
            metrics = SearchMetrics(float(i), 1.0, 10.0, 1, 0, 1, 1)
            collector.record_search(metrics)

        assert len(collector._metrics) == 2
        # Should have latencies 1.0 and 2.0 (last two)
        latencies = [m.latency_ms for m in collector._metrics]
        assert latencies == [1.0, 2.0]

    def test_reset(self, collector):
        """Test resetting all metrics."""
        # Add some data
        metrics = SearchMetrics(10.0, 1.0, 5.0, 2, 1, 5, 2)
        collector.record_search(metrics)
        collector.start_timer("test")

        # Reset
        collector.reset()

        assert len(collector._metrics) == 0
        assert len(collector._counters) == 0
        assert len(collector._timers) == 0


@pytest.mark.unit
class TestGlobalFunctions:
    """Test global metrics functions."""

    def test_get_metrics_collector(self):
        """Test getting global metrics collector."""
        collector = get_metrics_collector()
        assert isinstance(collector, MetricsCollector)

        # Should return same instance
        collector2 = get_metrics_collector()
        assert collector is collector2

    @patch("docs_mcp_server.search.metrics._metrics_collector")
    def test_record_search_metrics(self, mock_collector):
        """Test convenience function for recording metrics."""
        record_search_metrics(
            latency_ms=10.5,
            memory_mb=2.0,
            result_count=5,
            query_tokens=3,
        )

        # Verify SearchMetrics was created and recorded
        mock_collector.record_search.assert_called_once()
        call_args = mock_collector.record_search.call_args[0][0]

        assert call_args.latency_ms == 10.5
        assert call_args.memory_mb == 2.0
        assert call_args.cpu_percent == 0.0
        assert call_args.cache_hits == 0
        assert call_args.cache_misses == 0
        assert call_args.result_count == 5
        assert call_args.query_tokens == 3

    @patch("docs_mcp_server.search.metrics._metrics_collector")
    def test_record_search_metrics_defaults(self, mock_collector):
        """Test convenience function with default values."""
        record_search_metrics(latency_ms=5.0)

        call_args = mock_collector.record_search.call_args[0][0]
        assert call_args.latency_ms == 5.0
        assert call_args.memory_mb == 0.0
        assert call_args.result_count == 0
        assert call_args.query_tokens == 0
