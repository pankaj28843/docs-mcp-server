"""Unit tests for observability module."""

import json
import logging
from types import SimpleNamespace
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
    get_metrics_content_type,
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
from docs_mcp_server.observability.context import update_span_id, with_otel_span


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

    def test_json_default_handles_set_and_bytes(self):
        formatter = JsonFormatter()
        assert formatter._json_default({3, 1, 2}) == [1, 2, 3]
        assert formatter._json_default(b"ok") == "ok"

    def test_json_default_handles_unorderable_set(self):
        formatter = JsonFormatter()
        value = formatter._json_default({1, "a"})
        assert isinstance(value, list)
        assert len(value) == 2


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

    def test_update_span_id_preserves_trace_id(self):
        set_trace_context("aa" * 16, "bb" * 8, tenant="alpha")
        update_span_id("cc" * 8)
        ctx = get_trace_context()
        assert ctx["trace_id"] == "aa" * 16
        assert ctx["span_id"] == "cc" * 8
        assert ctx["tenant"] == "alpha"

    def test_with_otel_span_extracts_context(self):
        span_ctx = SimpleNamespace(trace_id=0x1234, span_id=0x5678)
        fake_span = SimpleNamespace(get_span_context=lambda: span_ctx)
        ctx = with_otel_span(fake_span)
        assert ctx["trace_id"].endswith("1234")
        assert ctx["span_id"].endswith("5678")


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

    def test_init_tracing_applies_resource_attributes(self):
        provider = init_tracing("test-service", resource_attributes={"service.version": "2.0.0"})
        assert provider.resource.attributes["service.version"] == "2.0.0"

    def test_get_tracer_initializes_when_missing(self):
        tracing_module._tracer_holder["tracer"] = None
        tracer = tracing_module.get_tracer()
        assert tracer is not None

    def test_build_trace_resource_attributes_none(self):
        assert build_trace_resource_attributes(None) == {}

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

    def test_configure_trace_exporter_inits_provider_when_missing(self, monkeypatch):
        config = ObservabilityCollectorConfig(enabled=True, otlp_protocol="http")

        class _Exporter:
            def shutdown(self):
                return None

        exporter = _Exporter()
        monkeypatch.setattr(tracing_module, "HttpOTLPSpanExporter", Mock(return_value=exporter))

        configure_trace_exporter(config, provider=object())

        assert tracing_module._tracer_holder["tracer"] is not None

    def test_configure_trace_exporter_handles_exporter_failure(self, monkeypatch):
        config = ObservabilityCollectorConfig(enabled=True, otlp_protocol="grpc")
        monkeypatch.setattr(tracing_module, "GrpcOTLPSpanExporter", Mock(side_effect=RuntimeError("boom")))

        configure_trace_exporter(config)

        assert metrics_module._OTLP_EXPORT_STATUS_PROM.labels(protocol="grpc")._value.get() == 0


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

    def test_configure_metrics_exporter_grpc(self, monkeypatch):
        metrics_module._meter_holder.update({"meter": None, "provider": None, "reader": None})
        captured: dict[str, str] = {}

        class FakeExporter:
            def __init__(self, *, endpoint, headers, timeout, insecure):
                captured["endpoint"] = endpoint
                self._preferred_temporality = None
                self._preferred_aggregation = None

            def shutdown(self, timeout_millis=30_000, **_kwargs):
                return None

        monkeypatch.setattr(metrics_module, "GrpcOTLPMetricExporter", FakeExporter)
        config = ObservabilityCollectorConfig(
            enabled=True,
            otlp_protocol="grpc",
            collector_endpoint="http://localhost:4317",
        )

        configure_metrics_exporter(config, service_name="test-service")

        assert captured["endpoint"] == "http://localhost:4317"

    def test_configure_metrics_exporter_replaces_provider_when_reader_missing(self, monkeypatch):
        metrics_module._meter_holder.update({"meter": None, "provider": None, "reader": None})
        provider = init_metrics("test-service")
        metrics_module._meter_holder["reader"] = None

        class FakeExporter:
            def __init__(self, *, endpoint, headers, timeout):
                self._preferred_temporality = None
                self._preferred_aggregation = None

            def shutdown(self, timeout_millis=30_000, **_kwargs):
                return None

        monkeypatch.setattr(metrics_module, "HttpOTLPMetricExporter", FakeExporter)
        config = ObservabilityCollectorConfig(enabled=True, otlp_protocol="http")

        configure_metrics_exporter(config, provider=provider)

        assert metrics_module._meter_holder["provider"] is not provider
        assert metrics_module._meter_holder["reader"] is not None

    def test_get_meter_initializes_when_missing(self):
        metrics_module._meter_holder.update({"meter": None, "provider": None, "reader": None})

        meter = metrics_module._get_meter()

        assert meter is not None

    def test_metric_bridge_unknown_kind_raises(self):
        bad_metric = metrics_module.MetricBridge(
            metrics_module._REQUEST_COUNT_PROM,
            otel_name="bad_metric",
            otel_description="bad",
            otel_kind="unknown",
        )
        with pytest.raises(ValueError, match="Unknown metric kind"):
            bad_metric.inc({"tenant": "test", "tool": "search", "status": "ok"}, 1.0)

    def test_get_metrics_content_type(self):
        assert get_metrics_content_type() == metrics_module.CONTENT_TYPE_LATEST


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

    def test_configure_log_exporter_grpc_and_handler_guard(self, monkeypatch):
        logging_module._logger_holder.update({"provider": None, "handler_added": False})
        captured: dict[str, str] = {}

        class FakeExporter:
            def __init__(self, *, endpoint, headers, timeout, insecure):
                captured["endpoint"] = endpoint

        class FakeProcessor:
            def __init__(self, exporter):
                self.exporter = exporter

            def shutdown(self):
                return None

            def on_emit(self, _record):
                return None

        monkeypatch.setattr(logging_module, "GrpcOTLPLogExporter", FakeExporter)
        monkeypatch.setattr(logging_module, "BatchLogRecordProcessor", FakeProcessor)
        monkeypatch.setattr(logging_module, "set_logger_provider", lambda _provider: None)
        config = ObservabilityCollectorConfig(
            enabled=True,
            otlp_protocol="grpc",
            collector_endpoint="http://collector:4317",
        )

        init_log_exporter("test-service")
        configure_log_exporter(config)

        assert captured["endpoint"] == "http://collector:4317"

        logging_module._logger_holder["handler_added"] = True
        handler_count = len(logging.getLogger().handlers)
        configure_log_exporter(config)
        assert len(logging.getLogger().handlers) == handler_count

    def test_init_log_exporter_applies_resource_attributes(self, monkeypatch):
        logging_module._logger_holder.update({"provider": None, "handler_added": False})
        monkeypatch.setattr(logging_module, "set_logger_provider", lambda _provider: None)
        provider = init_log_exporter("test-service", resource_attributes={"service.version": "1.2.3"})
        assert provider.resource.attributes["service.version"] == "1.2.3"

    def test_configure_log_exporter_inits_provider_when_missing(self, monkeypatch):
        logging_module._logger_holder.update({"provider": None, "handler_added": False})

        class FakeExporter:
            def __init__(self, *, endpoint, headers, timeout):
                pass

        class FakeProcessor:
            def __init__(self, exporter):
                self.exporter = exporter

            def on_emit(self, _record):
                return None

            def shutdown(self):
                return None

        monkeypatch.setattr(logging_module, "HttpOTLPLogExporter", FakeExporter)
        monkeypatch.setattr(logging_module, "BatchLogRecordProcessor", FakeProcessor)
        monkeypatch.setattr(logging_module, "set_logger_provider", lambda _provider: None)
        config = ObservabilityCollectorConfig(enabled=True, otlp_protocol="http")

        configure_log_exporter(config, provider=object())

        assert isinstance(logging_module._logger_holder["provider"], logging_module.LoggerProvider)


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

    async def test_trace_context_middleware_sets_tenant(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = tracing_module.TraceContextMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/django/search",
            "headers": [],
        }

        events = []

        async def send(message):
            events.append(message)

        await middleware(scope, None, send)

        ctx = get_trace_context()
        assert ctx.get("tenant") == "django"


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

    def test_configure_logging_non_json_formatter(self):
        configure_logging(level="INFO", json_output=False)
        root = logging.getLogger()
        formatter = root.handlers[0].formatter
        assert isinstance(formatter, logging.Formatter)
        assert "%(asctime)s" in formatter._style._fmt

    def test_configure_logging_trace_categories_and_overrides(self):
        configure_logging(
            level="INFO",
            trace_categories=["docs_mcp_server.trace"],
            logger_levels={"docs_mcp_server.trace": "ERROR"},
        )
        assert logging.getLogger("docs_mcp_server.trace").level == logging.ERROR
