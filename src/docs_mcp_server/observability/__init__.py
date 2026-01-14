"""Observability module for OpenTelemetry-aligned tracing, metrics, and logging."""

from docs_mcp_server.observability.context import get_trace_context, set_trace_context, trace_context
from docs_mcp_server.observability.logging import (
    JsonFormatter,
    configure_log_exporter,
    configure_logging,
    init_log_exporter,
)
from docs_mcp_server.observability.metrics import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    SEARCH_LATENCY,
    SEARCH_SNIPPET_SOURCE,
    configure_metrics_exporter,
    get_metrics,
    get_metrics_content_type,
    init_metrics,
    track_latency,
)
from docs_mcp_server.observability.tracing import (
    build_trace_resource_attributes,
    configure_trace_exporter,
    create_span,
    get_tracer,
    init_tracing,
)


__all__ = [
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "SEARCH_LATENCY",
    "SEARCH_SNIPPET_SOURCE",
    "JsonFormatter",
    "build_trace_resource_attributes",
    "configure_log_exporter",
    "configure_logging",
    "configure_metrics_exporter",
    "configure_trace_exporter",
    "create_span",
    "get_metrics",
    "get_metrics_content_type",
    "get_trace_context",
    "get_tracer",
    "init_log_exporter",
    "init_metrics",
    "init_tracing",
    "set_trace_context",
    "trace_context",
    "track_latency",
]
