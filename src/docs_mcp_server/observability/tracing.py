"""OpenTelemetry tracing with Starlette middleware."""

from __future__ import annotations

from contextlib import contextmanager
import logging
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GrpcOTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HttpOTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

from docs_mcp_server.deployment_config import ObservabilityCollectorConfig
from docs_mcp_server.observability.context import (
    generate_span_id,
    get_trace_context,
    set_trace_context,
    update_span_id,
)
from docs_mcp_server.observability.metrics import OTLP_EXPORT_ERRORS, OTLP_EXPORT_STATUS


if TYPE_CHECKING:
    from collections.abc import Generator

    from opentelemetry.trace import Span, Tracer
    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger(__name__)

# Module-level tracer storage
_tracer_holder: dict[str, Tracer | None] = {"tracer": None}


def init_tracing(
    service_name: str = "docs-mcp-server",
    resource_attributes: dict[str, str] | None = None,
) -> TracerProvider:
    """Initialize OpenTelemetry tracing."""
    attributes = {"service.name": service_name}
    if resource_attributes:
        attributes.update(resource_attributes)
    resource = Resource.create(attributes)
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)
    _tracer_holder["tracer"] = trace.get_tracer(__name__)
    logger.info("Tracing initialized for service: %s", service_name)
    return provider


def build_trace_resource_attributes(config: ObservabilityCollectorConfig | None) -> dict[str, str]:
    """Build resource attributes for trace export."""
    if not config:
        return {}

    return dict(config.resource_attributes)


def configure_trace_exporter(
    config: ObservabilityCollectorConfig | None,
    provider: TracerProvider | None = None,
) -> None:
    """Configure OTLP trace export for an initialized tracer provider."""
    if not config or not config.enabled:
        return

    active_provider = provider or trace.get_tracer_provider()
    if not isinstance(active_provider, TracerProvider):
        active_provider = init_tracing()

    protocol_label = config.otlp_protocol
    OTLP_EXPORT_STATUS.labels(protocol=protocol_label).set(0)

    try:
        if config.otlp_protocol == "grpc":
            exporter = GrpcOTLPSpanExporter(
                endpoint=config.collector_endpoint,
                headers=config.headers,
                timeout=config.timeout_seconds,
                insecure=config.grpc_insecure,
            )
        else:
            exporter = HttpOTLPSpanExporter(
                endpoint=config.collector_endpoint,
                headers=config.headers,
                timeout=config.timeout_seconds,
            )
    except Exception as exc:
        logger.error("Failed to configure OTLP exporter: %s", exc, exc_info=True)
        OTLP_EXPORT_ERRORS.labels(protocol=protocol_label).inc()
        return

    active_provider.add_span_processor(BatchSpanProcessor(exporter))
    OTLP_EXPORT_STATUS.labels(protocol=protocol_label).set(1)
    logger.info(
        "OTLP trace export enabled (%s) to %s",
        config.otlp_protocol,
        config.collector_endpoint,
    )


def _extract_tenant_from_path(path: str) -> str | None:
    if path.startswith("/") and "/" in path[1:]:
        potential_tenant = path.split("/")[1]
        if potential_tenant and potential_tenant not in ("mcp", "health", "metrics"):
            return potential_tenant
    return None


def get_tracer() -> Tracer:
    """Get the configured tracer."""
    if _tracer_holder["tracer"] is None:
        init_tracing()
    return _tracer_holder["tracer"]  # type: ignore[return-value]


@contextmanager
def create_span(
    name: str,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: dict[str, Any] | None = None,
) -> Generator[Span, None, None]:
    """Create a traced span with context propagation."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name, kind=kind) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)

        # Update context with new span_id
        ctx = span.get_span_context()
        update_span_id(format(ctx.span_id, "016x"))

        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


class TraceContextMiddleware:
    """Starlette middleware for trace context propagation."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract or generate trace context
        headers = dict(scope.get("headers", []))
        trace_id = headers.get(b"x-trace-id", b"").decode() or None
        if not trace_id:
            ctx = get_trace_context()
            trace_id = ctx["trace_id"]

        span_id = generate_span_id()
        set_trace_context(trace_id, span_id)

        # Extract tenant from path if present
        path = scope.get("path", "")
        tenant = _extract_tenant_from_path(path)
        if tenant:
            ctx = get_trace_context()
            set_trace_context(ctx["trace_id"], ctx["span_id"], tenant=tenant)

        await self.app(scope, receive, send)


async def trace_request(request: Request, call_next: Any) -> Response:
    """Middleware function for request tracing (alternative to class-based)."""
    attributes = {
        "http.method": request.method,
        "http.url": str(request.url),
        "http.route": request.url.path,
    }
    if request.url.path.startswith("/mcp"):
        attributes["mcp.endpoint"] = "root"
        attributes["mcp.transport"] = "http"
    tenant = _extract_tenant_from_path(request.url.path)
    if tenant:
        attributes["tenant.codename"] = tenant

    with create_span(
        "http.request",
        kind=SpanKind.SERVER,
        attributes=attributes,
    ) as span:
        span.add_event("http.request.start", {"http.method": request.method, "http.route": request.url.path})
        try:
            response: Response = await call_next(request)
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise

        span.set_attribute("http.status_code", response.status_code)
        span.add_event("http.request.end", {"http.status_code": response.status_code})
        if response.status_code >= 400:
            span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))
        return response
