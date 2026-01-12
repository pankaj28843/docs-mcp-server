"""Unit tests for observability module."""

import json
import logging

import pytest

from docs_mcp_server.observability import (
    JsonFormatter,
    configure_logging,
    create_span,
    get_metrics,
    get_trace_context,
    init_tracing,
    set_trace_context,
    track_latency,
)
from docs_mcp_server.observability.metrics import REQUEST_LATENCY


@pytest.mark.unit
class TestJsonFormatter:
    """Tests for structured JSON logging."""

    def test_format_includes_trace_context(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert data["message"] == "test message"
        assert data["level"] == "INFO"
        assert "timestamp" in data
        assert "trace_id" in data
        assert "span_id" in data

    def test_format_includes_extra_fields(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="error occurred",
            args=(),
            exc_info=None,
        )
        record.tenant = "django"
        output = formatter.format(record)
        data = json.loads(output)

        assert data["tenant"] == "django"


@pytest.mark.unit
class TestTraceContext:
    """Tests for trace context propagation."""

    def test_get_trace_context_generates_ids(self):
        ctx = get_trace_context()
        assert "trace_id" in ctx
        assert "span_id" in ctx
        assert len(ctx["trace_id"]) == 32
        assert len(ctx["span_id"]) == 16

    def test_set_trace_context_preserves_values(self):
        set_trace_context("abc123" * 5 + "ab", "def456" * 2 + "de", tenant="test")
        ctx = get_trace_context()
        assert ctx["trace_id"] == "abc123" * 5 + "ab"
        assert ctx["span_id"] == "def456" * 2 + "de"
        assert ctx.get("tenant") == "test"


@pytest.mark.unit
class TestTracing:
    """Tests for OpenTelemetry tracing."""

    def test_init_tracing_creates_tracer(self):
        init_tracing("test-service")
        # Should not raise

    def test_create_span_context_manager(self):
        init_tracing("test-service")
        with create_span("test.operation") as span:
            span.set_attribute("test.key", "value")
        # Should not raise


@pytest.mark.unit
class TestMetrics:
    """Tests for Prometheus metrics."""

    def test_get_metrics_returns_bytes(self):
        output = get_metrics()
        assert isinstance(output, bytes)
        assert b"mcp_request_latency_seconds" in output

    def test_track_latency_records_histogram(self):
        with track_latency(REQUEST_LATENCY, tenant="test", tool="search"):
            pass
        # Should not raise


@pytest.mark.unit
class TestConfigureLogging:
    """Tests for logging configuration."""

    def test_configure_logging_sets_level(self):
        configure_logging(level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_configure_logging_adds_handler(self):
        configure_logging(level="INFO")
        root = logging.getLogger()
        assert len(root.handlers) > 0
