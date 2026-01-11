"""Performance metrics collection for search operations."""

from collections import defaultdict, deque
from dataclasses import dataclass
import time


@dataclass
class SearchMetrics:
    """Search operation metrics."""

    latency_ms: float
    memory_mb: float
    cpu_percent: float
    cache_hits: int
    cache_misses: int
    result_count: int
    query_tokens: int


class MetricsCollector:
    """Lightweight metrics collector for search operations."""

    def __init__(self, window_size: int = 1000):
        self.window_size = window_size
        self._metrics = deque(maxlen=window_size)
        self._counters = defaultdict(int)
        self._timers = {}

    def start_timer(self, operation: str) -> str:
        """Start timing an operation."""
        timer_id = f"{operation}_{time.time()}"
        self._timers[timer_id] = time.perf_counter()
        return timer_id

    def end_timer(self, timer_id: str) -> float:
        """End timing and return duration in ms."""
        if timer_id not in self._timers:
            return 0.0

        duration = (time.perf_counter() - self._timers[timer_id]) * 1000
        del self._timers[timer_id]
        return duration

    def record_search(self, metrics: SearchMetrics):
        """Record search operation metrics."""
        self._metrics.append(metrics)
        self._counters["total_searches"] += 1

        if metrics.latency_ms > 10:
            self._counters["slow_searches"] += 1
        if metrics.result_count == 0:
            self._counters["empty_results"] += 1

    def get_stats(self) -> dict:
        """Get current performance statistics."""
        if not self._metrics:
            return {}

        latencies = [m.latency_ms for m in self._metrics]
        memory_usage = [m.memory_mb for m in self._metrics]
        result_counts = [m.result_count for m in self._metrics]

        return {
            "count": len(self._metrics),
            "latency": {
                "mean": sum(latencies) / len(latencies),
                "p95": sorted(latencies)[int(len(latencies) * 0.95)],
                "p99": sorted(latencies)[int(len(latencies) * 0.99)],
                "max": max(latencies),
            },
            "memory": {"mean": sum(memory_usage) / len(memory_usage), "max": max(memory_usage)},
            "results": {
                "mean": sum(result_counts) / len(result_counts),
                "empty_rate": self._counters["empty_results"] / self._counters["total_searches"],
            },
            "performance": {
                "slow_rate": self._counters["slow_searches"] / self._counters["total_searches"],
                "total_searches": self._counters["total_searches"],
            },
        }

    def reset(self):
        """Reset all metrics."""
        self._metrics.clear()
        self._counters.clear()
        self._timers.clear()


# Global metrics collector instance
_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector."""
    return _metrics_collector


def record_search_metrics(latency_ms: float, memory_mb: float = 0.0, result_count: int = 0, query_tokens: int = 0):
    """Convenience function to record search metrics."""
    metrics = SearchMetrics(
        latency_ms=latency_ms,
        memory_mb=memory_mb,
        cpu_percent=0.0,
        cache_hits=0,
        cache_misses=0,
        result_count=result_count,
        query_tokens=query_tokens,
    )
    _metrics_collector.record_search(metrics)
