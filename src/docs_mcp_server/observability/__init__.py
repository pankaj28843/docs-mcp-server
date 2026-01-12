"""Observability module for OpenTelemetry-aligned tracing, metrics, and logging."""

from docs_mcp_server.observability.context import get_trace_context, set_trace_context, trace_context
from docs_mcp_server.observability.logging import JsonFormatter, configure_logging
from docs_mcp_server.observability.metrics import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    SEARCH_LATENCY,
    get_metrics,
    get_metrics_content_type,
    track_latency,
)
from docs_mcp_server.observability.tracing import create_span, get_tracer, init_tracing


__all__ = [
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "SEARCH_LATENCY",
    "JsonFormatter",
    "configure_logging",
    "create_span",
    "get_metrics",
    "get_metrics_content_type",
    "get_trace_context",
    "get_tracer",
    "init_tracing",
    "set_trace_context",
    "trace_context",
    "track_latency",
]
