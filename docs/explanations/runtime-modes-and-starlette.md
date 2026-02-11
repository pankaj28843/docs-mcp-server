# Runtime modes and Starlette integration

This page explains how `online` and `offline` modes map to Starlette routing, middleware, lifespan, and FastMCP mounting.

## Why this matters

You should be able to answer, with source code open:

1. Which surfaces stay available in `offline` mode?
2. Which routes are intentionally blocked outside `online` mode?
3. Which Starlette primitives enforce those choices?

## Official docs we align with

- Starlette routing and `Mount`: https://www.starlette.dev/routing/
- Starlette middleware behavior: https://www.starlette.dev/middleware/
- Starlette lifespan semantics: https://www.starlette.dev/lifespan/
- Starlette exception handlers: https://www.starlette.dev/exceptions/
- FastMCP ASGI integration (`http_app` + lifespan note): https://gofastmcp.com/integrations/asgi/
- MCP tools contract: https://modelcontextprotocol.io/specification/2024-11-05/server/tools/
- MCP resources contract: https://modelcontextprotocol.io/specification/2024-11-05/server/resources/

## Runtime mode model in this project

`infrastructure.operation_mode` in `deployment.json` is read by `AppBuilder` and used to gate operational endpoints.

### Endpoint behavior matrix

| Surface | Offline | Online | Where enforced |
|---|---|---|---|
| `/mcp` (root MCP tools) | Available | Available | `AppBuilder._build_routes()` mount + `root_hub.http_app(...)` |
| `/health` and `/mcp.json` | Available | Available | `AppBuilder._build_core_routes()` |
| `/dashboard*` | 503 / unavailable | Available | `_build_dashboard_*_endpoint(operation_mode=...)` |
| `/{tenant}/sync/trigger` | 503 | Available | `_build_sync_trigger_endpoint(...)` |
| `/{tenant}/sync/retry-failed` | 503 | Available | `_build_retry_failed_endpoint(...)` |
| `/{tenant}/sync/purge-queue` | 503 | Available | `_build_purge_queue_endpoint(...)` |
| `/{tenant}/index/trigger` | 503 | Available | `_build_index_trigger_endpoint(...)` |

## How we exploit Starlette features

### Route and Mount composition

Starlette recommends route tables and sub-mounts; this project uses exactly that pattern.

- `Mount("/mcp", app=...)` isolates MCP transport from operational routes.
- `Route(...)` keeps health, dashboard, sync, and index endpoints explicit.
- Route grouping methods in `AppBuilder` keep the map readable during reviews.

### Lifespan-driven startup and teardown

Starlette guarantees request serving starts after lifespan startup and teardown runs after in-flight work.

In this project, `AppBuilder._build_lifespan_manager()`:

- initializes tenant apps before serving,
- enters FastMCP lifespan,
- drains tenant runtimes on signal/lifespan exit with timeout guards.

### Middleware and edge hardening

The app conditionally enables:

- `TrustedHostMiddleware` for host-header validation,
- `HTTPSRedirectMiddleware` for secure redirect enforcement,
- request tracing middleware for observability.

This keeps transport policy in one place instead of duplicated inside endpoints.

### Exception-handler boundary

`DatabaseCriticalError` is bound to one exception handler and translated to a 503 plus controlled process restart path. This preserves a consistent failure surface and avoids partial corruption after critical DB failures.

## FastMCP + Starlette integration pattern

FastMCP docs emphasize using `http_app(...)`, mounting in ASGI apps, and preserving lifespan behavior.

This server follows that pattern:

- builds one root hub via `create_root_hub(...)`,
- obtains ASGI transport app through `http_app(path="/", json_response=True, stateless_http=True)`,
- mounts it once at `/mcp`,
- manages lifespan from the top-level Starlette app.

## Alternatives considered

| Alternative | Why we did not choose it |
|---|---|
| Separate binaries for online/offline | Duplicates startup paths and increases drift risk |
| Ad-hoc `if offline` checks in each endpoint body only | Makes endpoint policy harder to audit at route-definition level |
| Custom router layer instead of Starlette primitives | Adds abstraction with little value over `Route` + `Mount` + middleware |

## Related

- [How-to: Evaluate runtime modes](../how-to/evaluate-runtime-modes.md)
- [Reference: Entrypoint walkthrough](../reference/entrypoint-walkthrough.md)
- [Reference: MCP tools API](../reference/mcp-tools.md)
