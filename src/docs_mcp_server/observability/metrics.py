"""Prometheus metrics for golden signals observability."""

from __future__ import annotations

from contextlib import contextmanager
import time
from typing import TYPE_CHECKING

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest


if TYPE_CHECKING:
    from collections.abc import Generator

# Golden signal metrics
REQUEST_LATENCY = Histogram(
    "mcp_request_latency_seconds",
    "Request latency in seconds",
    ["tenant", "tool"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

REQUEST_COUNT = Counter(
    "mcp_requests_total",
    "Total MCP requests",
    ["tenant", "tool", "status"],
)

ERROR_COUNT = Counter(
    "mcp_errors_total",
    "Total errors",
    ["tenant", "error_type", "component"],
)

ACTIVE_CONNECTIONS = Gauge(
    "mcp_active_connections",
    "Active connections",
    ["tenant"],
)

# Search-specific metrics
SEARCH_LATENCY = Histogram(
    "search_latency_seconds",
    "Search query latency",
    ["tenant"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
)

INDEX_DOC_COUNT = Gauge(
    "index_document_count",
    "Documents in index",
    ["tenant"],
)


@contextmanager
def track_latency(histogram: Histogram, **labels: str) -> Generator[None, None, None]:
    """Context manager to track operation latency."""
    start = time.perf_counter()
    try:
        yield
    finally:
        histogram.labels(**labels).observe(time.perf_counter() - start)


def get_metrics() -> bytes:
    """Generate Prometheus metrics output."""
    return generate_latest()


def get_metrics_content_type() -> str:
    """Get content type for metrics endpoint."""
    return CONTENT_TYPE_LATEST
