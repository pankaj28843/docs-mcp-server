"""Context propagation for trace correlation across async boundaries."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING
from uuid import uuid4


if TYPE_CHECKING:
    from opentelemetry.trace import Span

# Thread-safe context for trace propagation
trace_context: ContextVar[dict | None] = ContextVar("trace_context", default=None)


def generate_trace_id() -> str:
    """Generate a 32-char hex trace ID."""
    return uuid4().hex


def generate_span_id() -> str:
    """Generate a 16-char hex span ID."""
    return uuid4().hex[:16]


def get_trace_context() -> dict:
    """Get current trace context with trace_id and span_id."""
    ctx = trace_context.get()
    if ctx is None or not ctx.get("trace_id"):
        ctx = {"trace_id": generate_trace_id(), "span_id": generate_span_id()}
        trace_context.set(ctx)
    return ctx


def set_trace_context(trace_id: str, span_id: str, **extra: object) -> None:
    """Set trace context for current async context."""
    trace_context.set({"trace_id": trace_id, "span_id": span_id, **extra})


def update_span_id(span_id: str) -> None:
    """Update span_id while preserving trace_id."""
    ctx = trace_context.get() or {}
    trace_context.set({**ctx, "span_id": span_id})


def with_otel_span(span: Span) -> dict:
    """Extract trace context from OpenTelemetry span."""
    ctx = span.get_span_context()
    return {
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
    }
