# Runtime modes and Starlette integration

This page explains how the server behaves in `online` vs `offline` mode, and how that behavior is implemented with Starlette + FastMCP.

## Why this matters

For demos, onboarding, and incident response, people need to answer two questions quickly:

1. Which endpoints and background behaviors are active in each mode?
2. Where in source code does that behavior live?

## Official docs we align with

- Starlette applications, routing, middleware, and lifespan:
  - https://www.starlette.dev/applications/
  - https://www.starlette.dev/routing/
  - https://www.starlette.dev/middleware/
  - https://www.starlette.dev/lifespan/
- FastMCP ASGI integration and `http_app()`:
  - https://gofastmcp.com/integrations/asgi/
  - https://gofastmcp.com/servers/server/
- MCP tools/resources protocol model:
  - https://modelcontextprotocol.io/specification/2024-11-05/server/tools/
  - https://modelcontextprotocol.io/specification/2024-11-05/server/resources/

## Runtime mode model in this project

The mode is configured in `deployment.json` under `infrastructure.operation_mode` and consumed in `src/docs_mcp_server/app_builder.py`.

### `online` mode

`online` mode enables operational endpoints and scheduler workflows for tenants that support syncing.

Examples of online-only behavior in route handlers:

- `/dashboard` UI routes are enabled.
- `/{tenant}/sync/trigger` supports sync operations.
- `/{tenant}/sync/retry-failed` and queue-management routes are enabled.
- `/{tenant}/index/trigger` is available for on-demand indexing.

### `offline` mode

`offline` mode keeps retrieval/search endpoints alive but blocks mutation/sync surfaces.

The app still serves:

- `/mcp` (root hub tools)
- `/health`
- `/mcp.json`
- read-only tenant search/fetch paths through MCP tools

The app returns mode-aware failures for mutation or dashboard-only actions.

## How Starlette features are used

This project deliberately leans on Starlette primitives instead of bespoke routing layers.

### 1) Route + Mount composition

Implementation: `src/docs_mcp_server/app_builder.py`

- Root MCP hub is mounted at `/mcp` using `Mount`.
- Operational endpoints use explicit `Route` definitions.
- This mirrors Starlette’s recommended route-table composition style.

### 2) Lifespan for startup/shutdown orchestration

Implementation: `AppBuilder._build_lifespan_manager()` in `src/docs_mcp_server/app_builder.py`

- Tenants are initialized before request serving.
- Shutdown drains and background tasks are coordinated in one lifecycle path.
- This follows Starlette’s guidance that serving starts after lifespan startup completes.

### 3) Middleware for edge hardening

Implementation: `src/docs_mcp_server/app_builder.py`

- `TrustedHostMiddleware` is enabled when configured.
- `HTTPSRedirectMiddleware` is enabled when configured.
- Request tracing middleware is attached for observability.

### 4) Exception handlers for critical failures

Implementation: `src/docs_mcp_server/app_builder.py`

- `DatabaseCriticalError` is mapped to a controlled 503 response and process exit path.
- This keeps failure handling centralized and observable.

## FastMCP integration pattern

Implementation: `src/docs_mcp_server/app_builder.py`

- Root hub is built via `create_root_hub(...)`.
- FastMCP HTTP app is mounted once (`/mcp`) and tenant routing is delegated through hub tools.
- This is aligned with FastMCP ASGI integration guidance using `http_app(...)` with Starlette mounting.

## Design rationale for online vs offline split

- `online`: full operator control plane (sync/index/dashboard) for actively managed docs infra.
- `offline`: safe retrieval-only mode for deterministic demos, local experiments, and reduced side effects.
- A single app graph with mode gates is easier to reason about than maintaining separate server binaries.

## Source pointers for walkthroughs

- Entrypoint: `src/docs_mcp_server/app.py`
- App wiring: `src/docs_mcp_server/app_builder.py`
- Root MCP hub tools: `src/docs_mcp_server/root_hub.py`
- Tenant composition: `src/docs_mcp_server/tenant.py`
- Runtime health endpoint: `src/docs_mcp_server/runtime/health.py`
