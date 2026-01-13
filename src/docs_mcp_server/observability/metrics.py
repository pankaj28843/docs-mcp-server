"""Prometheus metrics for golden signals observability with OTLP export."""

from __future__ import annotations

from contextlib import contextmanager
import time
from typing import TYPE_CHECKING, Any

from opentelemetry import metrics as otel_metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter as GrpcOTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter as HttpOTLPMetricExporter,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from docs_mcp_server.deployment_config import ObservabilityCollectorConfig


if TYPE_CHECKING:
    from collections.abc import Generator


_meter_holder: dict[str, Any] = {"meter": None, "provider": None, "reader": None}


def init_metrics(
    service_name: str = "docs-mcp-server",
    resource_attributes: dict[str, str] | None = None,
    metric_readers: list[PeriodicExportingMetricReader] | None = None,
) -> MeterProvider:
    """Initialize OpenTelemetry metrics."""
    provider = _meter_holder.get("provider")
    if isinstance(provider, MeterProvider):
        return provider

    attributes = {"service.name": service_name}
    if resource_attributes:
        attributes.update(resource_attributes)
    resource = Resource.create(attributes)
    provider = MeterProvider(resource=resource, metric_readers=metric_readers or [])
    otel_metrics.set_meter_provider(provider)
    _meter_holder["provider"] = provider
    _meter_holder["meter"] = otel_metrics.get_meter(__name__)
    return provider


def configure_metrics_exporter(
    config: ObservabilityCollectorConfig | None,
    provider: MeterProvider | None = None,
    *,
    service_name: str = "docs-mcp-server",
    resource_attributes: dict[str, str] | None = None,
) -> None:
    """Configure OTLP metrics export for an initialized meter provider."""
    if not config or not config.enabled:
        return

    endpoint = config.collector_endpoint
    if config.otlp_protocol == "http" and endpoint.endswith("/v1/traces"):
        endpoint = endpoint.removesuffix("/v1/traces") + "/v1/metrics"

    if config.otlp_protocol == "grpc":
        exporter = GrpcOTLPMetricExporter(
            endpoint=endpoint,
            headers=config.headers,
            timeout=config.timeout_seconds,
            insecure=config.grpc_insecure,
        )
    else:
        exporter = HttpOTLPMetricExporter(
            endpoint=endpoint,
            headers=config.headers,
            timeout=config.timeout_seconds,
        )

    reader = PeriodicExportingMetricReader(exporter)

    active_provider = provider or _meter_holder.get("provider")
    if not isinstance(active_provider, MeterProvider):
        active_provider = init_metrics(
            service_name=service_name,
            resource_attributes=resource_attributes,
            metric_readers=[reader],
        )
        _meter_holder["reader"] = reader
        return

    if _meter_holder.get("reader") is None:
        resource = getattr(active_provider, "resource", None) or getattr(active_provider, "_resource", None)
        if resource is None:
            resource = Resource.create({})
        replacement = MeterProvider(resource=resource, metric_readers=[reader])
        otel_metrics.set_meter_provider(replacement)
        _meter_holder["provider"] = replacement
        _meter_holder["meter"] = otel_metrics.get_meter(__name__)
        _meter_holder["reader"] = reader


def _get_meter():
    meter = _meter_holder.get("meter")
    if meter is None:
        init_metrics()
        meter = _meter_holder.get("meter")
    return meter


def _label_key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(labels.items()))


class _BoundMetric:
    def __init__(self, wrapper: MetricBridge, labels: dict[str, str]) -> None:
        self._wrapper = wrapper
        self._labels = labels

    def inc(self, amount: float = 1.0) -> None:
        self._wrapper.inc(self._labels, amount)

    def observe(self, value: float) -> None:
        self._wrapper.observe(self._labels, value)

    def set(self, value: float) -> None:
        self._wrapper.set(self._labels, value)


class MetricBridge:
    """Bridge Prometheus metrics to optional OTel instruments."""

    def __init__(
        self,
        prom_metric: Counter | Histogram | Gauge,
        *,
        otel_name: str,
        otel_description: str,
        otel_kind: str,
    ) -> None:
        self._prom_metric = prom_metric
        self._otel_name = otel_name
        self._otel_description = otel_description
        self._otel_kind = otel_kind
        self._otel_instrument = None
        self._last_values: dict[tuple[tuple[str, str], ...], float] = {}

    def labels(self, **labels: str) -> _BoundMetric:
        return _BoundMetric(self, labels)

    def _ensure_otel_instrument(self):
        if self._otel_instrument is not None:
            return self._otel_instrument
        meter = _get_meter()
        if self._otel_kind == "counter":
            self._otel_instrument = meter.create_counter(self._otel_name, description=self._otel_description)
        elif self._otel_kind == "histogram":
            self._otel_instrument = meter.create_histogram(self._otel_name, description=self._otel_description)
        elif self._otel_kind == "gauge":
            self._otel_instrument = meter.create_up_down_counter(self._otel_name, description=self._otel_description)
        else:
            raise ValueError(f"Unknown metric kind: {self._otel_kind}")
        return self._otel_instrument

    def inc(self, labels: dict[str, str], amount: float) -> None:
        self._prom_metric.labels(**labels).inc(amount)
        otel = self._ensure_otel_instrument()
        otel.add(amount, labels)

    def observe(self, labels: dict[str, str], value: float) -> None:
        self._prom_metric.labels(**labels).observe(value)
        otel = self._ensure_otel_instrument()
        otel.record(value, labels)

    def set(self, labels: dict[str, str], value: float) -> None:
        self._prom_metric.labels(**labels).set(value)
        otel = self._ensure_otel_instrument()
        key = _label_key(labels)
        last = self._last_values.get(key, 0.0)
        delta = value - last
        if delta:
            otel.add(delta, labels)
        self._last_values[key] = value


# Golden signal metrics (Prometheus + OTLP)
_REQUEST_LATENCY_PROM = Histogram(
    "mcp_request_latency_seconds",
    "Request latency in seconds",
    ["tenant", "tool"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

_REQUEST_COUNT_PROM = Counter(
    "mcp_requests_total",
    "Total MCP requests",
    ["tenant", "tool", "status"],
)

_ERROR_COUNT_PROM = Counter(
    "mcp_errors_total",
    "Total errors",
    ["tenant", "error_type", "component"],
)

_ACTIVE_CONNECTIONS_PROM = Gauge(
    "mcp_active_connections",
    "Active connections",
    ["tenant"],
)

_SEARCH_LATENCY_PROM = Histogram(
    "search_latency_seconds",
    "Search query latency",
    ["tenant"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
)

_INDEX_DOC_COUNT_PROM = Gauge(
    "index_document_count",
    "Documents in index",
    ["tenant"],
)

_OTLP_EXPORT_ERRORS_PROM = Counter(
    "otlp_export_errors_total",
    "Total OTLP export configuration errors",
    ["protocol"],
)

_OTLP_EXPORT_STATUS_PROM = Gauge(
    "otlp_exporter_enabled",
    "OTLP exporter enabled status (1=enabled, 0=disabled)",
    ["protocol"],
)

REQUEST_LATENCY = MetricBridge(
    _REQUEST_LATENCY_PROM,
    otel_name="mcp_request_latency_seconds",
    otel_description="Request latency in seconds",
    otel_kind="histogram",
)

REQUEST_COUNT = MetricBridge(
    _REQUEST_COUNT_PROM,
    otel_name="mcp_requests_total",
    otel_description="Total MCP requests",
    otel_kind="counter",
)

ERROR_COUNT = MetricBridge(
    _ERROR_COUNT_PROM,
    otel_name="mcp_errors_total",
    otel_description="Total errors",
    otel_kind="counter",
)

ACTIVE_CONNECTIONS = MetricBridge(
    _ACTIVE_CONNECTIONS_PROM,
    otel_name="mcp_active_connections",
    otel_description="Active connections",
    otel_kind="gauge",
)

SEARCH_LATENCY = MetricBridge(
    _SEARCH_LATENCY_PROM,
    otel_name="search_latency_seconds",
    otel_description="Search query latency",
    otel_kind="histogram",
)

INDEX_DOC_COUNT = MetricBridge(
    _INDEX_DOC_COUNT_PROM,
    otel_name="index_document_count",
    otel_description="Documents in index",
    otel_kind="gauge",
)

OTLP_EXPORT_ERRORS = MetricBridge(
    _OTLP_EXPORT_ERRORS_PROM,
    otel_name="otlp_export_errors_total",
    otel_description="Total OTLP export configuration errors",
    otel_kind="counter",
)

OTLP_EXPORT_STATUS = MetricBridge(
    _OTLP_EXPORT_STATUS_PROM,
    otel_name="otlp_exporter_enabled",
    otel_description="OTLP exporter enabled status (1=enabled, 0=disabled)",
    otel_kind="gauge",
)


@contextmanager
def track_latency(histogram: MetricBridge, **labels: str) -> Generator[None, None, None]:
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
