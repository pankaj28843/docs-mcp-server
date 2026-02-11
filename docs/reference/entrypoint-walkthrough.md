# Entrypoint walkthrough

This is the source-level guide for following the request path from process startup to MCP tool execution.

## Official references

- Uvicorn settings and programmatic startup:
  - https://uvicorn.dev/settings/
- Starlette application/routing/lifespan model:
  - https://www.starlette.dev/applications/
  - https://www.starlette.dev/routing/
  - https://www.starlette.dev/lifespan/
- FastMCP ASGI integration:
  - https://gofastmcp.com/integrations/asgi/

## Startup call graph

1. Python module entrypoint
   - `src/docs_mcp_server/__main__.py`
   - delegates directly to `docs_mcp_server.app.main()`
2. Process runtime bootstrap
   - `src/docs_mcp_server/app.py`
   - resolves config path, loads deployment config, configures logging, runs Uvicorn
3. App construction
   - `src/docs_mcp_server/app.py:create_app()`
   - uses `AppBuilder(...).build()`
4. Route and runtime wiring
   - `src/docs_mcp_server/app_builder.py`
   - builds Starlette routes, middleware, lifespan, and exception handlers
5. MCP root hub
   - `src/docs_mcp_server/root_hub.py`
   - registers root tools (`list_tenants`, `find_tenant`, `describe_tenant`, `root_search`, `root_fetch`)
6. Tenant composition
   - `src/docs_mcp_server/tenant.py`
   - builds per-tenant retrieval/sync services and adapters

## Entrypoint helper structure

`src/docs_mcp_server/app.py` now separates startup concerns into focused helpers:

- `_resolve_config_path()`
- `_resolve_log_level(...)`
- `_load_runtime_config(...)`
- `load_runtime_config(...)`
- `_configure_process_logging(...)`
- `_log_startup(...)`
- `_run_uvicorn(...)`

This keeps `main()` readable and easy to review.

## AppBuilder route map structure

`src/docs_mcp_server/app_builder.py` organizes Starlette route wiring in three route groups:

- `_build_core_routes(...)`
  - `/health`, `/metrics`, `/mcp.json`, `/tenants/status`, `/{tenant}/sync/status`
- `_build_dashboard_routes(operation_mode=...)`
  - `/dashboard` and tenant dashboard/event endpoints
- `_build_sync_routes(operation_mode=...)`
  - sync/index mutation endpoints

Plus one `Mount("/mcp", app=...)` for FastMCP transport.

This grouping makes mode-gated behavior easy to inspect during walkthroughs.

## Minimal source-reading order

Use this order for architecture review and onboarding:

1. `src/docs_mcp_server/app.py`
2. `src/docs_mcp_server/app_builder.py`
3. `src/docs_mcp_server/root_hub.py`
4. `src/docs_mcp_server/tenant.py`
5. `src/docs_mcp_server/search/bm25_engine.py`

## Runtime mode checkpoints

While reading `AppBuilder`, validate these checkpoints:

- route mount for `/mcp` root hub
- `/health` and `/mcp.json` operational introspection
- mode-gated online endpoints (sync/index/dashboard)
- middleware and lifecycle wiring

Use this as your “explain with code open” script during deep-dive demos.

## MCP tool execution path (single request)

For one `root_search` request:

1. Client sends MCP request to `/mcp`.
2. Mounted FastMCP app dispatches tool call into `root_hub` handlers.
3. `src/docs_mcp_server/root_hub.py` validates tenant and arguments.
4. Tenant services execute retrieval/search path.
5. Tool response returns through FastMCP transport.

Related references:

- [Reference: MCP tools API](mcp-tools.md)
- [Explanation: Runtime modes and Starlette](../explanations/runtime-modes-and-starlette.md)
