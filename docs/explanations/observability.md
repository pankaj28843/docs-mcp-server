# Observability

The docs-mcp-server includes production-grade observability with OpenTelemetry-aligned tracing, structured logging, and Prometheus metrics.

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `/metrics` | Prometheus metrics in text format |
| `/health` | Health check endpoint |

## Structured Logging

All logs are emitted as JSON with trace correlation:

```json
{
  "timestamp": "2026-01-12T22:29:07.429878+00:00",
  "level": "INFO",
  "message": "Search completed",
  "logger": "docs_mcp_server.search",
  "trace_id": "625f5e96e1e24618a58fb2e291f7574d",
  "span_id": "46a0ed11012f4ec6",
  "component": "search",
  "tenant": "django"
}
```

Fields:
- `trace_id`: 32-char hex ID correlating all logs in a request
- `span_id`: 16-char hex ID for the current operation
- `component`: Module name (extracted from logger)
- `tenant`: Tenant codename when available

## Metrics

Golden signal metrics exposed at `/metrics`:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `mcp_request_latency_seconds` | Histogram | tenant, tool | Request latency |
| `mcp_requests_total` | Counter | tenant, tool, status | Total requests |
| `mcp_errors_total` | Counter | tenant, error_type, component | Total errors |
| `search_latency_seconds` | Histogram | tenant | Search query latency |
| `index_document_count` | Gauge | tenant | Documents in index |

## Tracing

OpenTelemetry tracing is enabled by default. Trace boundaries:

- HTTP requests via `TraceContextMiddleware`
- MCP tool calls (`mcp.tool.*` spans)
- Search queries (`search.query` spans)

Trace context propagates via `contextvars` across async boundaries.

## Configuration

Observability is initialized automatically in `AppBuilder.build()`. The log level follows `infrastructure.log_level` in deployment.json.

To disable JSON logging for local development, set environment variable:
```bash
export LOG_FORMAT=text
```
