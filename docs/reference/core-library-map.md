# Core library map

This reference maps core dependencies to where they are used in the codebase and why they were chosen.

## Official docs (TechDocs-backed)

- FastMCP server + ASGI integration:
  - https://gofastmcp.com/servers/server/
  - https://gofastmcp.com/integrations/asgi/
- MCP spec: https://modelcontextprotocol.io/specification/2024-11-05/server/tools/
- Starlette: https://www.starlette.dev/applications/
- Uvicorn: https://uvicorn.dev/settings/
- Pydantic: https://docs.pydantic.dev/latest/concepts/models/
- Python asyncio: https://docs.python.org/3.13/library/asyncio-eventloop.html
- uv (project/dependency runner): https://docs.astral.sh/uv/guides/projects/
- Pytest: https://docs.pytest.org/en/stable/how-to/usage.html
- Ruff: https://docs.astral.sh/ruff/settings/
- MkDocs config: https://www.mkdocs.org/user-guide/configuration/
- SQLite (WAL): https://www.sqlite.org/wal.html
- SQLite (FTS5): https://www.sqlite.org/fts5.html
- OpenTelemetry OTLP spec: https://opentelemetry.io/docs/specs/otlp/
- Playwright Python: https://playwright.dev/python/docs/browsers
- Jinja templates: https://jinja.palletsprojects.com/en/stable/templates/

## TechDocs coverage notes

- `aiohttp` and `httpx` are core dependencies in `pyproject.toml` but do not currently have dedicated TechDocs tenants in this environment.
- For those two libraries, use official upstream docs directly during deep dives.

## Architecture evidence matrix

| Concern | Official guidance | Project implementation |
|---|---|---|
| ASGI app composition | Starlette `Route`/`Mount` composition | `src/docs_mcp_server/app_builder.py` |
| MCP transport embedding | FastMCP `http_app(...)` in ASGI app | `src/docs_mcp_server/app_builder.py`, `src/docs_mcp_server/root_hub.py` |
| Tool contracts | MCP tools schema, `tools/list`, `tools/call` | `src/docs_mcp_server/root_hub.py` |
| Startup validation | Pydantic `ValidationError` on config parsing | `src/docs_mcp_server/deployment_config.py`, `src/docs_mcp_server/app.py` |
| Process runtime knobs | Uvicorn host/port/log/worker/concurrency settings | `src/docs_mcp_server/app.py` |
| Project command isolation | `uv run` project-scoped execution | `README.md`, CI, local scripts |

## Runtime stack

| Library | Role in this project | Primary code paths |
|---|---|---|
| `fastmcp` | MCP tool server abstraction and HTTP app integration | `src/docs_mcp_server/root_hub.py`, `src/docs_mcp_server/app_builder.py` |
| `mcp` (protocol) | Tool/resource protocol contracts and client interoperability | `src/docs_mcp_server/root_hub.py`, external MCP clients |
| `starlette` | ASGI app shell: routes, middleware, lifespan | `src/docs_mcp_server/app_builder.py`, `src/docs_mcp_server/app.py` |
| `uvicorn` | ASGI process server and runtime limits | `src/docs_mcp_server/app.py` |
| `pydantic` | Deployment config/schema validation and error surfaces | `src/docs_mcp_server/deployment_config.py`, `src/docs_mcp_server/app.py` |
| `python` (`asyncio`) | Event loop and async lifecycle primitives behind ASGI stack | async runtimes, scheduler services, fetch workflows |

## Search and content pipeline

| Library | Role in this project | Primary code paths |
|---|---|---|
| `article-extractor` | HTML-to-article extraction for crawled pages | crawler/fetcher utilities and sync pipeline |
| `playwright` | JS-rendered page fetch fallback and crawler debugging | fetcher/crawler utilities, `debug_multi_tenant.py` workflows |
| `lxml` / `html2text` / `justhtml` | HTML parsing and normalization | fetcher + indexing preprocessors |
| SQLite + internal BM25 engine | Retrieval ranking and segment storage | `src/docs_mcp_server/search/bm25_engine.py`, `src/docs_mcp_server/search/sqlite_storage.py` |

## Ops and observability

| Library | Role in this project | Primary code paths |
|---|---|---|
| `opentelemetry-*` | tracing/metrics/log export integration | `src/docs_mcp_server/observability/` |
| `prometheus-client` | metrics exposition for `/metrics` | `src/docs_mcp_server/observability/metrics.py` |

## Quality and docs toolchain

| Library | Role in this project | Primary code paths |
|---|---|---|
| `pytest` | unit/integration test runner, marker filtering | `tests/`, CI workflow |
| `ruff` | formatting + linting in validation loop | repo-wide via `pyproject.toml` |
| `uv` | deterministic command runner and environment manager (`uv run ...`) | validation scripts, local workflows, CI steps |
| `mkdocs` + `mkdocs-material` | docs site generation and navigation | `mkdocs.yml`, `docs/` |
| `jinja2` | dashboard/template rendering in web UI | `src/docs_mcp_server/ui/templates/`, `src/docs_mcp_server/ui/dashboard.py` |

## Why this mix works

- Starlette gives explicit ASGI control for mode-gated operational routes.
- FastMCP and MCP spec alignment keep tool interfaces interoperable.
- Pydantic keeps startup failures deterministic and debuggable.
- Uvicorn provides the operational knobs we need (`workers`, concurrency limits, logging control).
- SQLite keeps search storage local, inspectable, and portable.
- Pytest + Ruff + MkDocs strict mode keep the “code + docs + tests” story cohesive for contributors.

## Common pitfalls

| Pitfall | Why it hurts | What to do instead |
|---|---|---|
| Treating FastMCP as a separate service binary by default | Splits lifecycle and middleware policy | Keep FastMCP mounted in Starlette app |
| Hiding route behavior in custom abstractions | Harder to trace endpoint ownership and policy | Keep routes explicit in `AppBuilder` route groups |
| Adding docs commands you did not run | Drifts from reality quickly | Run command in current session, then document it |
| Mixing tutorial/how-to/reference content | Newcomers cannot find the right path quickly | Keep strict Divio quadrant boundaries |
