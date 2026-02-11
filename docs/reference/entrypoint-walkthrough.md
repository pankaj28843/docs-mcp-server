# Entrypoint walkthrough

This is the source-level guide for newcomers who want to follow the real request path from process startup to MCP tool execution.

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
- `_load_runtime_config(...)`
- `_configure_process_logging(...)`
- `_log_startup(...)`
- `_run_uvicorn(...)`

This keeps `main()` readable and easier to present in live walkthroughs.

## Minimal source-reading order for talks

For a lightning talk or onboarding session:

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
