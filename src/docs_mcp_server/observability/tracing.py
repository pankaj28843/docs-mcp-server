"""OpenTelemetry tracing with Starlette middleware."""

from __future__ import annotations

from contextlib import contextmanager
import logging
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode

from docs_mcp_server.observability.context import (
    generate_span_id,
    get_trace_context,
    set_trace_context,
    update_span_id,
)


if TYPE_CHECKING:
    from collections.abc import Generator

    from opentelemetry.trace import Span, Tracer
    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger(__name__)

# Module-level tracer storage
_tracer_holder: dict[str, Tracer | None] = {"tracer": None}


def init_tracing(service_name: str = "docs-mcp-server") -> None:
    """Initialize OpenTelemetry tracing."""
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)
    _tracer_holder["tracer"] = trace.get_tracer(__name__)
    logger.info("Tracing initialized for service: %s", service_name)


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
        if path.startswith("/") and "/" in path[1:]:
            potential_tenant = path.split("/")[1]
            if potential_tenant and potential_tenant not in ("mcp", "health", "metrics"):
                ctx = get_trace_context()
                set_trace_context(ctx["trace_id"], ctx["span_id"], tenant=potential_tenant)

        await self.app(scope, receive, send)


async def trace_request(request: Request, call_next: Any) -> Response:
    """Middleware function for request tracing (alternative to class-based)."""
    with create_span(
        "http.request",
        kind=SpanKind.SERVER,
        attributes={
            "http.method": request.method,
            "http.url": str(request.url),
            "http.route": request.url.path,
        },
    ) as span:
        response: Response = await call_next(request)
        span.set_attribute("http.status_code", response.status_code)
        if response.status_code >= 400:
            span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))
        return response
