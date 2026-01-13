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

When OTLP export is enabled, logs are also shipped via OTLP to SigNoz using the same collector settings. [#techdocs](https://signoz.io/docs/instrumentation/python/)

## Metrics

Golden signal metrics exposed at `/metrics`:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `mcp_request_latency_seconds` | Histogram | tenant, tool | Request latency |
| `mcp_requests_total` | Counter | tenant, tool, status | Total requests |
| `mcp_errors_total` | Counter | tenant, error_type, component | Total errors |
| `search_latency_seconds` | Histogram | tenant | Search query latency |
| `index_document_count` | Gauge | tenant | Documents in index |

When OTLP export is enabled, these metrics are also exported via OTLP to SigNoz (no Prometheus scrape required). [#techdocs](https://signoz.io/docs/instrumentation/python/)

## Tracing

OpenTelemetry tracing is enabled by default. Trace boundaries:

- HTTP requests via `TraceContextMiddleware`
- MCP tool calls (`mcp.tool.*` spans)
- Search queries (`search.query` spans)

Trace context propagates via `contextvars` across async boundaries.

### Trace export

OTLP export is opt-in. Configure `infrastructure.observability_collector` in `deployment.json` to send traces to SigNoz via OTLP gRPC (default `http://localhost:4317`) or OTLP HTTP (`http://localhost:4318/v1/traces`). Env-driven single-tenant mode does not expose collector settings, so you must use `deployment.json` to enable export. [#techdocs](https://signoz.io/docs/install/docker/)

Use `resource_attributes` in the collector config to attach OpenTelemetry resource attributes (for example, `service.version`, `deployment.environment`). [#techdocs](https://signoz.io/docs/instrumentation/python/)

### SigNoz helper

The repo includes `scripts/signoz-observability-restart` for restarting/upgrading a local SigNoz deployment via Docker Compose. The script clones the SigNoz repo (shallow), updates to the requested version, and runs `docker compose up -d --remove-orphans`. [#techdocs](https://signoz.io/docs/install/docker/) [#techdocs](https://docs.docker.com/reference/cli/docker/compose/up/)

### SigNoz provisioning

Use `scripts/signoz-provision.py` to replay dashboard and alert rule provisioning. This orchestrates `scripts/signoz-dashboards-sync.py` and `scripts/signoz-alerts-sync.py` and supports API key or session-token auth (see script help for env vars). [#techdocs](https://signoz.io/docs/userguide/dashboards/) [#techdocs](https://signoz.io/docs/userguide/alerts-management/)

`deploy_multi_tenant.py` runs SigNoz provisioning when `SIGNOZ_PROVISION=true` and OTLP export is enabled.

## Configuration

Observability is initialized automatically in `AppBuilder.build()`. The log level follows `infrastructure.log_level` in deployment.json.

To disable JSON logging for local development, set environment variable:
```bash
export LOG_FORMAT=text
```
