"""Unit tests for observability module."""

import json
import logging
from unittest.mock import Mock

from opentelemetry import trace as trace_api
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricExportResult
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
import pytest
from starlette.requests import Request
from starlette.responses import Response

from docs_mcp_server.deployment_config import ObservabilityCollectorConfig
from docs_mcp_server.observability import (
    REQUEST_COUNT,
    REQUEST_LATENCY,
    JsonFormatter,
    build_trace_resource_attributes,
    configure_log_exporter,
    configure_logging,
    configure_metrics_exporter,
    configure_trace_exporter,
    create_span,
    get_metrics,
    get_trace_context,
    init_log_exporter,
    init_metrics,
    init_tracing,
    logging as logging_module,
    metrics as metrics_module,
    set_trace_context,
    tracing as tracing_module,
    track_latency,
)


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

    def test_format_truncates_and_redacts(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="x" * 5000,
            args=(),
            exc_info=None,
        )
        record.api_key = "secret"
        output = formatter.format(record)
        data = json.loads(output)

        assert data["message"].endswith("...")
        assert data["api_key"] == "[REDACTED]"


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

    def test_build_trace_resource_attributes_returns_resource_attributes(self):
        config = ObservabilityCollectorConfig(
            resource_attributes={"service.version": "1.0.0"},
        )
        attributes = build_trace_resource_attributes(config)
        assert attributes == {"service.version": "1.0.0"}

    def test_configure_trace_exporter_adds_span_processor(self, monkeypatch):
        provider = init_tracing("test-service")
        config = ObservabilityCollectorConfig(
            enabled=True,
            otlp_protocol="http",
            collector_endpoint="http://collector/v1/traces",
        )
        exporter = object()
        monkeypatch.setattr(tracing_module, "HttpOTLPSpanExporter", Mock(return_value=exporter))
        add_processor = Mock()
        provider.add_span_processor = add_processor  # type: ignore[method-assign]

        configure_trace_exporter(config, provider=provider)

        add_processor.assert_called_once()


@pytest.mark.unit
class TestMetricsExport:
    def test_init_metrics_creates_provider(self):
        metrics_module._meter_holder.update({"meter": None, "provider": None, "reader": None})
        provider = init_metrics("test-service", {"service.version": "1.0.0"})
        assert isinstance(provider, MeterProvider)

        REQUEST_COUNT.labels(tenant="test", tool="list_tenants", status="ok").inc()
        REQUEST_LATENCY.labels(tenant="test", tool="list_tenants").observe(0.25)

    def test_configure_metrics_exporter_http_rewrites_endpoint(self, monkeypatch):
        metrics_module._meter_holder.update({"meter": None, "provider": None, "reader": None})
        captured: dict[str, str] = {}

        class FakeExporter:
            def __init__(self, *, endpoint, headers, timeout):
                self.endpoint = endpoint
                captured["endpoint"] = endpoint
                self._preferred_temporality = None
                self._preferred_aggregation = None

            def export(self, metrics_data, timeout_millis=10_000, **kwargs):
                return MetricExportResult.SUCCESS

            def force_flush(self, timeout_millis=10_000):
                return True

            def shutdown(self, timeout_millis=30_000, **kwargs):
                return None

        monkeypatch.setattr(metrics_module, "HttpOTLPMetricExporter", FakeExporter)
        config = ObservabilityCollectorConfig(
            enabled=True,
            otlp_protocol="http",
            collector_endpoint="http://localhost:4318/v1/traces",
        )

        configure_metrics_exporter(config, service_name="test-service")

        assert captured["endpoint"] == "http://localhost:4318/v1/metrics"


@pytest.mark.unit
class TestLogExport:
    def test_configure_log_exporter_http_rewrites_endpoint(self, monkeypatch):
        logging_module._logger_holder.update({"provider": None, "handler_added": False})
        captured: dict[str, str] = {}

        class FakeExporter:
            def __init__(self, *, endpoint, headers, timeout):
                self.endpoint = endpoint
                captured["endpoint"] = endpoint

        class FakeProcessor:
            def __init__(self, exporter):
                self.exporter = exporter

            def shutdown(self):
                return None

        monkeypatch.setattr(logging_module, "HttpOTLPLogExporter", FakeExporter)
        monkeypatch.setattr(logging_module, "BatchLogRecordProcessor", FakeProcessor)
        config = ObservabilityCollectorConfig(
            enabled=True,
            otlp_protocol="http",
            collector_endpoint="http://localhost:4318/v1/traces",
        )

        init_log_exporter("test-service")
        configure_log_exporter(config)

        assert captured["endpoint"] == "http://localhost:4318/v1/logs"


@pytest.mark.unit
@pytest.mark.asyncio
class TestTraceRequestMiddleware:
    """Tests for HTTP request tracing middleware."""

    @staticmethod
    def _make_request(path: str) -> Request:
        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 123),
        }
        return Request(scope)

    @staticmethod
    def _setup_exporter() -> InMemorySpanExporter:
        exporter = InMemorySpanExporter()
        provider = trace_api.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = init_tracing("test-service")
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        return exporter

    async def test_trace_request_sets_attributes_and_tenant(self):
        exporter = self._setup_exporter()

        request = self._make_request("/drf/search")

        async def call_next(_: Request) -> Response:
            return Response("ok", status_code=200)

        await tracing_module.trace_request(request, call_next)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "http.request"
        assert span.attributes["http.method"] == "GET"
        assert span.attributes["http.route"] == "/drf/search"
        assert span.attributes["tenant.codename"] == "drf"
        assert span.attributes["http.status_code"] == 200

    async def test_trace_request_marks_error_on_http_error(self):
        exporter = self._setup_exporter()

        request = self._make_request("/drf/search")

        async def call_next(_: Request) -> Response:
            return Response("nope", status_code=404)

        await tracing_module.trace_request(request, call_next)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.status.status_code == StatusCode.ERROR
        assert span.attributes["http.status_code"] == 404

    async def test_trace_request_marks_error_on_exception(self):
        exporter = self._setup_exporter()

        request = self._make_request("/drf/search")

        async def call_next(_: Request) -> Response:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await tracing_module.trace_request(request, call_next)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.status.status_code == StatusCode.ERROR


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
